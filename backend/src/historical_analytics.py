"""
historical_analytics.py  —  ChainIQ START Hack 2026
====================================================
Pure-pandas analytics over historical_awards.csv and requests.json.
No LLM calls. Runs on startup and feeds two things:

  1. EscalationCycleAnalyzer   — per-type approval cycle time statistics
  2. ConcentrationRiskMonitor  — portfolio-level supplier concentration (HHI)

Both modules produce structured objects that:
  (a) get embedded in the pipeline output for every new request
  (b) feed the ApprovalRouter SLA predictions with REAL historical data
      instead of hardcoded constants

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MODULE 1: EscalationCycleAnalyzer
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DATA SOURCES
  historical_awards.csv  →  award_date, escalation_required, escalated_to,
                             request_id, awarded
  requests.json          →  created_at  (joined on request_id)

CYCLE TIME DEFINITION
  cycle_days = award_date − created_at
  This is the total time from request submission to sourcing decision.
  For escalated requests it includes the escalation resolution time.
  For non-escalated requests it is the baseline automated processing time.

WHAT IT COMPUTES PER ESCALATION TYPE
  n                 number of historical cases
  mean_days         arithmetic mean cycle time
  median_days       p50 — used as the "expected" time in SLA predictions
  p75_days          upper-quartile — planning buffer
  p90_days          90th percentile — worst-case SLA commitment
  p95_days          extreme tail — flags for SLA breach risk
  std_days          standard deviation
  min_days / max_days
  pct_on_time       % of cases resolved within the policy target (14 days)
  trend_direction   "IMPROVING" | "STABLE" | "WORSENING" over last 90 days
  trend_delta_days  how many days faster/slower vs the prior period

ESCALATION TYPES (from escalated_to field in historical_awards.csv)
  "Requester"                  → ER-001 (missing info)
  "Procurement Manager"        → ER-002 (restricted supplier)
  "Head of Strategic Sourcing" → ER-003 / ER-004 (high value / no supplier)
  "Head of Category"           → ER-004
  "Security/Compliance Lead"   → ER-005 (data residency)
  "Sourcing Excellence Lead"   → ER-006 (capacity)
  "Marketing Governance Lead"  → ER-007 (brand safety)
  "Regional Compliance Lead"   → ER-008 (registration)
  None / not escalated         → baseline (automated decisions)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MODULE 2: ConcentrationRiskMonitor
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DATA SOURCES
  historical_awards.csv  →  supplier_id, supplier_name, total_value,
                             awarded=True, category_l1, category_l2
  merged_v2.csv          →  region (joined on supplier_id + category)

METRIC: HERFINDAHL-HIRSCHMAN INDEX (HHI)
  HHI = Σ (market_share_i × 100)²   over awarded suppliers in a segment
  Range: 0 — 10,000
    HHI < 1,500    COMPETITIVE      — healthy supplier diversity
    1,500–2,500    MODERATE         — watch list
    HHI > 2,500    CONCENTRATED     — intervention recommended
    HHI = 10,000   MONOPOLY         — single source, critical risk

  Market share = supplier_i awarded value / total awarded value in segment
  Segment = (category_l2, region)

ADDITIONAL METRICS PER SEGMENT
  top_supplier_share_pct    largest single-supplier share
  n_active_suppliers        count with any awarded value
  single_source_risk        True if n_active_suppliers == 1
  dependency_flag           True if top_supplier_share_pct > 40%

WHAT COUNTS AS A NEW AWARD
  For real-time use: the monitor takes a proposed new award and recomputes
  post-award HHI instantly, showing before/after to the decision-maker.

INTEGRATION
━━━━━━━━━━━

  from historical_analytics import EscalationCycleAnalyzer, ConcentrationRiskMonitor

  # On pipeline startup (once):
  cycle_analyzer = EscalationCycleAnalyzer(data_dir="data/")
  concentration  = ConcentrationRiskMonitor(data_dir="data/")

  # Per request — in pipeline.run() after rule engine:
  sla = cycle_analyzer.predict_sla(escalation_targets)
  engine_output["sla_prediction"] = sla

  # Per request — concentration impact of the proposed award:
  impact = concentration.award_impact(
      supplier_id   = top_supplier["supplier_id"],
      category_l2   = request["category_l2"],
      region        = delivery_region,
      award_value   = contract_value_eur,
  )
  engine_output["concentration_impact"] = impact
"""

from __future__ import annotations

import json
import warnings
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from pandas.errors import SettingWithCopyWarning
    warnings.filterwarnings("ignore", category=SettingWithCopyWarning)
except ImportError:
    # Fallback for older/different pandas versions
    pass

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

# Policy target: all sourcing decisions should close within 14 calendar days
POLICY_TARGET_DAYS = 14

# HHI thresholds (standard antitrust / procurement governance thresholds)
HHI_COMPETITIVE  = 1_500
HHI_MODERATE     = 2_500

# Single-supplier dependency flag threshold
MAX_SINGLE_SUPPLIER_SHARE = 40.0   # %

# Trend window: compare last 90 days vs prior 90 days
TREND_WINDOW_DAYS = 90

FX_TO_EUR = {"EUR": 1.0, "CHF": 1.04, "USD": 0.92}

COUNTRY_TO_REGION = {
    "DE": "EU", "FR": "EU", "NL": "EU", "BE": "EU", "AT": "EU",
    "IT": "EU", "ES": "EU", "PL": "EU", "UK": "EU",
    "CH": "CH",
    "US": "Americas", "CA": "Americas", "BR": "Americas", "MX": "Americas",
    "SG": "APAC", "AU": "APAC", "IN": "APAC", "JP": "APAC",
    "UAE": "MEA", "ZA": "MEA",
}

def _to_eur(amount: float, currency: str) -> float:
    return amount * FX_TO_EUR.get(str(currency).upper(), 1.0)


# ══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CycleProfile:
    """Statistics for one escalation type (or the no-escalation baseline)."""
    escalation_target:  str          # e.g. "Procurement Manager" or "baseline"
    rule_codes:         list[str]    # e.g. ["ER-002"]
    n:                  int          # number of historical cases
    mean_days:          float
    median_days:        float
    p75_days:           float
    p90_days:           float
    p95_days:           float
    std_days:           float
    min_days:           float
    max_days:           float
    pct_on_time:        float        # % resolved ≤ POLICY_TARGET_DAYS
    trend_direction:    str          # IMPROVING | STABLE | WORSENING
    trend_delta_days:   float        # + = getting slower, - = getting faster
    insufficient_data:  bool         # True if n < 5


@dataclass
class SLAPrediction:
    """SLA forecast for a specific new request given its escalation targets."""
    request_escalation_targets: list[str]
    worst_case_target:          str      # the slowest escalation type
    expected_days:              float    # median of worst-case type
    p90_days:                   float    # p90 of worst-case type
    policy_target_days:         int      # always POLICY_TARGET_DAYS
    sla_status:                 str      # OK | TIGHT | CRITICAL
    sla_detail:                 str
    parallel_routing_advised:   bool
    per_target_profiles:        list[dict]   # CycleProfile per target


@dataclass
class SegmentConcentration:
    """Concentration metrics for one (category_l2, region) segment."""
    category_l2:            str
    region:                 str
    n_active_suppliers:     int
    total_awarded_eur:      float
    hhi:                    float          # 0–10,000
    hhi_label:              str            # COMPETITIVE | MODERATE | CONCENTRATED | MONOPOLY
    top_supplier_id:        str
    top_supplier_name:      str
    top_supplier_share_pct: float
    top_3_share_pct:        float          # CR3 concentration ratio
    dependency_flag:        bool           # top share > MAX_SINGLE_SUPPLIER_SHARE
    single_source_risk:     bool           # only 1 active supplier
    supplier_shares:        list[dict]     # [{supplier_name, share_pct, value_eur}]


@dataclass
class ConcentrationImpact:
    """Before/after concentration metrics for a proposed new award."""
    supplier_id:        str
    supplier_name:      str
    category_l2:        str
    region:             str
    award_value_eur:    float

    # Before
    hhi_before:         float
    share_before_pct:   float
    label_before:       str

    # After
    hhi_after:          float
    share_after_pct:    float
    label_after:        str

    # Change
    hhi_delta:          float
    crosses_threshold:  bool     # HHI crosses a band boundary
    dependency_flag_new: bool    # share > 40% after award
    recommendation:     str      # action text for auditors


# ══════════════════════════════════════════════════════════════════════════════
# MODULE 1: ESCALATION CYCLE ANALYZER
# ══════════════════════════════════════════════════════════════════════════════

# Maps escalated_to string → ER rule codes (for annotation only)
ESCALATION_RULE_MAP: dict[str, list[str]] = {
    "Requester":                  ["ER-001"],
    "Procurement Manager":        ["ER-002"],
    "Head of Strategic Sourcing": ["ER-003", "ER-004"],
    "Head of Category":           ["ER-004"],
    "Security/Compliance Lead":   ["ER-005"],
    "Sourcing Excellence Lead":   ["ER-006"],
    "Marketing Governance Lead":  ["ER-007"],
    "Regional Compliance Lead":   ["ER-008"],
}


class EscalationCycleAnalyzer:
    """
    Computes per-escalation-type cycle time statistics from
    historical_awards.csv joined with requests.json created_at timestamps.

    On init: loads data and builds the full CycleProfile table.
    At request time: call predict_sla(escalation_targets) for instant SLA forecast.
    """

    def __init__(self, data_dir: str | Path = "data"):
        self.data_dir = Path(data_dir)
        self._profiles: dict[str, CycleProfile] = {}
        self._df: pd.DataFrame = pd.DataFrame()
        self._load_and_build()

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────────────────

    def profiles(self) -> dict[str, CycleProfile]:
        """All computed cycle profiles, keyed by escalation_target."""
        return self._profiles

    def profile_for(self, escalation_target: str) -> CycleProfile | None:
        return self._profiles.get(escalation_target)

    def cycle_stats_for_target(
        self,
        escalation_target: str,
        business_unit: str | None = None,
    ) -> dict[str, Any]:
        """
        Return cycle statistics for a target, optionally scoped to business unit.
        Falls back to all-BU statistics if scoped sample is too small.
        """
        if self._df.empty:
            return {"mean_days": 0.0, "median_days": 0.0, "n": 0, "scoped_to_business_unit": False}

        df = self._df.copy()
        if escalation_target == "baseline":
            subset = df[
                (df["escalation_required"] == False) |
                (df["escalated_to"].isna())
            ]
        else:
            subset = df[df["escalated_to"].astype(str).str.strip() == escalation_target]

        scoped = False
        if business_unit and "business_unit" in subset.columns:
            bu_subset = subset[
                subset["business_unit"].astype(str).str.strip().str.lower()
                == str(business_unit).strip().lower()
            ]
            # Avoid noisy advice from very low-N slices
            if len(bu_subset) >= 3:
                subset = bu_subset
                scoped = True

        if subset.empty:
            return {"mean_days": 0.0, "median_days": 0.0, "n": 0, "scoped_to_business_unit": False}

        vals = subset["cycle_days"].astype(float)
        return {
            "mean_days": round(float(vals.mean()), 1),
            "median_days": round(float(vals.median()), 1),
            "n": int(len(vals)),
            "scoped_to_business_unit": scoped,
        }

    def predict_sla(
        self,
        escalation_targets: list[str],
        days_to_deadline: int | None = None,
    ) -> SLAPrediction:
        """
        Given the escalation targets fired for a new request, predict the
        expected cycle time and assess SLA risk.

        escalation_targets: list of escalated_to strings from the rule engine
                            (empty list = no escalation, use baseline)
        days_to_deadline:   calendar days between now and required_by_date
        """
        if not escalation_targets:
            targets_to_check = ["baseline"]
        else:
            targets_to_check = escalation_targets

        # Find the worst-case (slowest) profile among active escalation types
        per_target = []
        worst: CycleProfile | None = None

        for target in targets_to_check:
            profile = self._profiles.get(target) or self._profiles.get("baseline")
            if profile:
                per_target.append(asdict(profile))
                if worst is None or profile.p90_days > worst.p90_days:
                    worst = profile

        if worst is None:
            # No historical data at all — use conservative defaults
            worst = CycleProfile(
                escalation_target="unknown",
                rule_codes=[],
                n=0,
                mean_days=10.0, median_days=10.0,
                p75_days=14.0,  p90_days=21.0, p95_days=28.0,
                std_days=5.0,   min_days=1.0,  max_days=45.0,
                pct_on_time=60.0,
                trend_direction="STABLE", trend_delta_days=0.0,
                insufficient_data=True,
            )

        # SLA assessment
        sla_status, sla_detail, parallel = self._assess_sla(
            worst, days_to_deadline
        )

        return SLAPrediction(
            request_escalation_targets=escalation_targets,
            worst_case_target=worst.escalation_target,
            expected_days=worst.median_days,
            p90_days=worst.p90_days,
            policy_target_days=POLICY_TARGET_DAYS,
            sla_status=sla_status,
            sla_detail=sla_detail,
            parallel_routing_advised=parallel,
            per_target_profiles=per_target,
        )

    def _assess_sla(
        self,
        worst: CycleProfile,
        days_to_deadline: int | None,
    ) -> tuple[str, str, bool]:
        base = (
            f"'{worst.escalation_target}' escalations historically close in "
            f"{worst.median_days:.1f}d (median) / {worst.p90_days:.1f}d (p90), "
            f"n={worst.n}."
        )
        if worst.trend_direction == "WORSENING":
            base += f" ⚠ Trend: +{worst.trend_delta_days:.1f}d slower than prior period."
        elif worst.trend_direction == "IMPROVING":
            base += f" ✓ Trend: -{abs(worst.trend_delta_days):.1f}d faster than prior period."

        if days_to_deadline is None:
            return "UNKNOWN", base + " Deadline not specified.", False

        if days_to_deadline >= worst.p90_days + 2:
            return "OK", base + f" {days_to_deadline}d available — comfortable margin.", False
        elif days_to_deadline >= worst.median_days:
            return (
                "TIGHT",
                base + f" Only {days_to_deadline}d available. "
                "Recommend parallel routing to all approvers simultaneously.",
                True,
            )
        else:
            return (
                "CRITICAL",
                base + f" Only {days_to_deadline}d available — "
                "below historical median. Standard sequential process INFEASIBLE. "
                "Escalate immediately with explicit deadline waiver request.",
                True,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # PRINT REPORT
    # ─────────────────────────────────────────────────────────────────────────

    def print_report(self) -> None:
        print("\n" + "═" * 76)
        print("ESCALATION CYCLE TIME ANALYSIS")
        print(f"Policy target: ≤{POLICY_TARGET_DAYS} calendar days")
        print("═" * 76)
        print(f"{'Escalation target':<32} {'n':>4}  {'median':>7}  {'p90':>7}  "
              f"{'on-time':>8}  {'trend':>10}")
        print("─" * 76)

        # Print baseline first, then sorted by p90 descending
        ordered = (
            [("baseline", self._profiles["baseline"])]
            if "baseline" in self._profiles else []
        ) + [
            (k, v) for k, v in
            sorted(self._profiles.items(), key=lambda x: x[1].p90_days, reverse=True)
            if k != "baseline"
        ]

        for _, p in ordered:
            if p.insufficient_data:
                suffix = " (low n)"
            else:
                suffix = ""
            trend_icon = {"IMPROVING": "▼", "STABLE": "─", "WORSENING": "▲"}.get(
                p.trend_direction, "─"
            )
            trend_str = f"{trend_icon} {abs(p.trend_delta_days):.1f}d"
            print(
                f"  {p.escalation_target:<30} {p.n:>4}  "
                f"{p.median_days:>6.1f}d  {p.p90_days:>6.1f}d  "
                f"{p.pct_on_time:>7.0f}%  {trend_str:>10}{suffix}"
            )

        print("─" * 76)
        print("Trend: ▼ faster  ─ stable  ▲ slower  (vs prior 90-day window)")
        print("═" * 76)

    # ─────────────────────────────────────────────────────────────────────────
    # INTERNAL: load data and build profiles
    # ─────────────────────────────────────────────────────────────────────────

    def _load_and_build(self) -> None:
        awards  = self._load_awards()
        requests_created = self._load_request_dates()

        if awards.empty:
            print("[EscalationCycleAnalyzer] No awards data — using defaults.")
            return

        # Join awards with request created_at
        df = awards.merge(requests_created, on="request_id", how="left")

        # Compute cycle_days
        df["award_dt"]   = pd.to_datetime(df["award_date"],   errors="coerce", utc=True)
        df["created_dt"] = pd.to_datetime(df["created_at"],   errors="coerce", utc=True)
        df["cycle_days"] = (df["award_dt"] - df["created_dt"]).dt.days

        # Drop rows with missing or negative cycle times
        df = df.dropna(subset=["cycle_days"])
        df = df[df["cycle_days"] >= 0]

        # Keep only awarded=True rows (one row per request = the winning bid)
        df_awarded = df[df["awarded"] == True].copy()
        if df_awarded.empty:
            df_awarded = df.copy()   # fallback: use all rows

        self._df = df_awarded

        # Build baseline profile (non-escalated requests)
        baseline_df = df_awarded[
            (df_awarded["escalation_required"] == False) |
            (df_awarded["escalated_to"].isna())
        ]
        if not baseline_df.empty:
            self._profiles["baseline"] = self._build_profile(
                "baseline", [], baseline_df["cycle_days"]
            )

        # Build per-escalation-target profiles
        escalated_df = df_awarded[df_awarded["escalation_required"] == True]

        for target, rule_codes in ESCALATION_RULE_MAP.items():
            subset = escalated_df[
                escalated_df["escalated_to"].astype(str).str.strip() == target
            ]["cycle_days"]
            self._profiles[target] = self._build_profile(
                target, rule_codes, subset
            )

        # Also catch any escalation targets in the data not in our map
        for target in escalated_df["escalated_to"].dropna().unique():
            if target not in self._profiles:
                subset = escalated_df[
                    escalated_df["escalated_to"] == target
                ]["cycle_days"]
                self._profiles[str(target)] = self._build_profile(
                    str(target), [], subset
                )

    def _build_profile(
        self,
        target: str,
        rule_codes: list[str],
        series: pd.Series,
    ) -> CycleProfile:
        """Compute all statistics for a single escalation type."""
        n = len(series)
        insufficient = n < 5

        if n == 0:
            return CycleProfile(
                escalation_target=target, rule_codes=rule_codes, n=0,
                mean_days=0, median_days=0, p75_days=0, p90_days=0,
                p95_days=0, std_days=0, min_days=0, max_days=0,
                pct_on_time=100.0,
                trend_direction="STABLE", trend_delta_days=0.0,
                insufficient_data=True,
            )

        vals = series.astype(float)

        # Trend: compare last TREND_WINDOW_DAYS vs prior period
        trend_dir, trend_delta = self._compute_trend(target)

        return CycleProfile(
            escalation_target=target,
            rule_codes=rule_codes,
            n=n,
            mean_days=round(float(vals.mean()), 1),
            median_days=round(float(vals.median()), 1),
            p75_days=round(float(vals.quantile(0.75)), 1),
            p90_days=round(float(vals.quantile(0.90)), 1),
            p95_days=round(float(vals.quantile(0.95)), 1),
            std_days=round(float(vals.std()), 1),
            min_days=round(float(vals.min()), 1),
            max_days=round(float(vals.max()), 1),
            pct_on_time=round(
                float((vals <= POLICY_TARGET_DAYS).mean() * 100), 1
            ),
            trend_direction=trend_dir,
            trend_delta_days=trend_delta,
            insufficient_data=insufficient,
        )

    def _compute_trend(self, target: str) -> tuple[str, float]:
        """Compare median cycle time: last 90 days vs prior 90 days."""
        if self._df.empty or "award_dt" not in self._df.columns:
            return "STABLE", 0.0

        df = self._df.copy()
        if target == "baseline":
            df = df[
                (df["escalation_required"] == False) |
                (df["escalated_to"].isna())
            ]
        else:
            df = df[df["escalated_to"].astype(str).str.strip() == target]

        if df.empty or "award_dt" not in df.columns:
            return "STABLE", 0.0

        cutoff    = df["award_dt"].max()
        recent    = df[df["award_dt"] >= cutoff - pd.Timedelta(days=TREND_WINDOW_DAYS)]
        prior     = df[
            (df["award_dt"] <  cutoff - pd.Timedelta(days=TREND_WINDOW_DAYS)) &
            (df["award_dt"] >= cutoff - pd.Timedelta(days=TREND_WINDOW_DAYS * 2))
        ]

        if len(recent) < 3 or len(prior) < 3:
            return "STABLE", 0.0

        recent_median = recent["cycle_days"].median()
        prior_median  = prior["cycle_days"].median()
        delta         = round(float(recent_median - prior_median), 1)

        if delta > 1.5:
            return "WORSENING", delta
        elif delta < -1.5:
            return "IMPROVING", delta
        else:
            return "STABLE", delta

    # ─────────────────────────────────────────────────────────────────────────
    # DATA LOADING
    # ─────────────────────────────────────────────────────────────────────────

    def _load_awards(self) -> pd.DataFrame:
        for p in [
            self.data_dir / "historical_awards.csv",
            self.data_dir / "../data/historical_awards.csv",
        ]:
            if p.exists():
                try:
                    df = pd.read_csv(p)
                    # Normalise boolean
                    if "awarded" in df.columns:
                        df["awarded"] = df["awarded"].astype(str).str.strip().str.lower().isin(
                            ["true", "1", "yes"]
                        )
                    if "escalation_required" in df.columns:
                        df["escalation_required"] = (
                            df["escalation_required"].astype(str).str.strip().str.lower()
                            .isin(["true", "1", "yes"])
                        )
                    return df
                except Exception as e:
                    print(f"[EscalationCycleAnalyzer] Load error: {e}")
        return pd.DataFrame()

    def _load_request_dates(self) -> pd.DataFrame:
        """Load request_id, created_at, business_unit from requests.json."""
        for p in [
            self.data_dir / "requests.json",
            self.data_dir / "../data/requests.json",
        ]:
            if p.exists():
                try:
                    reqs = json.loads(p.read_text())
                    return pd.DataFrame([
                        {"request_id": r.get("request_id"),
                         "created_at": r.get("created_at"),
                         "business_unit": r.get("business_unit")}
                        for r in reqs
                        if r.get("request_id") and r.get("created_at")
                    ])
                except Exception as e:
                    print(f"[EscalationCycleAnalyzer] requests.json error: {e}")
        return pd.DataFrame(columns=["request_id", "created_at", "business_unit"])


# ══════════════════════════════════════════════════════════════════════════════
# MODULE 2: CONCENTRATION RISK MONITOR
# ══════════════════════════════════════════════════════════════════════════════

def _hhi_label(hhi: float) -> str:
    if hhi >= 10_000:
        return "MONOPOLY"
    elif hhi >= HHI_MODERATE:
        return "CONCENTRATED"
    elif hhi >= HHI_COMPETITIVE:
        return "MODERATE"
    else:
        return "COMPETITIVE"


class ConcentrationRiskMonitor:
    """
    Computes Herfindahl-Hirschman Index (HHI) per (category_l2, region)
    segment from historical awarded contracts.

    On init: builds the full portfolio concentration table.
    At request time: call award_impact() to get before/after HHI for a
    proposed new award — the result travels in the pipeline output JSON.
    """

    def __init__(self, data_dir: str | Path = "data"):
        self.data_dir = Path(data_dir)
        self._segments: dict[tuple[str, str], SegmentConcentration] = {}
        self._raw: pd.DataFrame = pd.DataFrame()
        self._load_and_build()

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────────────────

    def segments(self) -> list[SegmentConcentration]:
        return list(self._segments.values())

    def segment(self, category_l2: str, region: str) -> SegmentConcentration | None:
        return self._segments.get((category_l2, region))

    def award_impact(
        self,
        supplier_id: str,
        supplier_name: str,
        category_l2: str,
        region: str,
        award_value_eur: float,
    ) -> ConcentrationImpact:
        """
        Compute how adding this award changes the HHI for the segment.
        Returns a ConcentrationImpact with before/after metrics and
        a plain-English recommendation for the audit record.
        """
        seg = self._segments.get((category_l2, region))

        if seg is None:
            # Segment has no history — this would be a new segment
            return ConcentrationImpact(
                supplier_id=supplier_id,
                supplier_name=supplier_name,
                category_l2=category_l2,
                region=region,
                award_value_eur=award_value_eur,
                hhi_before=0.0,
                share_before_pct=0.0,
                label_before="NO DATA",
                hhi_after=10_000.0,
                share_after_pct=100.0,
                label_after="MONOPOLY",
                hhi_delta=10_000.0,
                crosses_threshold=True,
                dependency_flag_new=True,
                recommendation=(
                    f"No historical awarded spend in {category_l2} / {region}. "
                    f"Awarding to {supplier_name} would establish a single-source "
                    f"dependency. Recommend competitive RFQ before committing."
                ),
            )

        # Current supplier share in this segment
        current_supplier_value = sum(
            s["value_eur"] for s in seg.supplier_shares
            if s.get("supplier_id") == supplier_id
        )

        total_before    = seg.total_awarded_eur
        total_after     = total_before + award_value_eur
        sup_after_value = current_supplier_value + award_value_eur

        share_before_pct = (
            (current_supplier_value / total_before * 100)
            if total_before > 0 else 0.0
        )
        share_after_pct = sup_after_value / total_after * 100 if total_after > 0 else 100.0

        # Recompute HHI after the award
        hhi_before = seg.hhi
        hhi_after  = self._recompute_hhi(
            seg.supplier_shares, supplier_id, award_value_eur, total_after
        )

        hhi_delta   = hhi_after - hhi_before
        label_before = seg.hhi_label
        label_after  = _hhi_label(hhi_after)

        crosses = _hhi_label(hhi_before) != label_after
        dep_flag = share_after_pct > MAX_SINGLE_SUPPLIER_SHARE

        recommendation = self._build_recommendation(
            supplier_name, category_l2, region,
            hhi_before, hhi_after, label_after,
            share_after_pct, dep_flag, crosses
        )

        return ConcentrationImpact(
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            category_l2=category_l2,
            region=region,
            award_value_eur=round(award_value_eur, 2),
            hhi_before=round(hhi_before, 0),
            share_before_pct=round(share_before_pct, 1),
            label_before=label_before,
            hhi_after=round(hhi_after, 0),
            share_after_pct=round(share_after_pct, 1),
            label_after=label_after,
            hhi_delta=round(hhi_delta, 0),
            crosses_threshold=crosses,
            dependency_flag_new=dep_flag,
            recommendation=recommendation,
        )

    def _recompute_hhi(
        self,
        shares: list[dict],
        new_sup_id: str,
        new_value: float,
        new_total: float,
    ) -> float:
        """Recompute HHI after adding a new award to the segment."""
        updated: dict[str, float] = {}
        for s in shares:
            sid = s.get("supplier_id", s.get("supplier_name", "?"))
            updated[sid] = updated.get(sid, 0.0) + s.get("value_eur", 0.0)
        updated[new_sup_id] = updated.get(new_sup_id, 0.0) + new_value

        if new_total <= 0:
            return 0.0

        hhi = sum((v / new_total * 100) ** 2 for v in updated.values())
        return round(hhi, 1)

    def _build_recommendation(
        self,
        name: str, cat: str, region: str,
        hhi_before: float, hhi_after: float, label_after: str,
        share_after: float, dep_flag: bool, crosses: bool,
    ) -> str:
        parts = [
            f"Awarding to {name} changes {cat} / {region} "
            f"HHI: {hhi_before:.0f} → {hhi_after:.0f} ({label_after})."
        ]
        if label_after == "MONOPOLY":
            parts.append(
                "CRITICAL: Single-source dependency. Mandatory competitive review required."
            )
        elif label_after == "CONCENTRATED":
            if crosses:
                parts.append(
                    "WARNING: Crosses into CONCENTRATED range (>2,500). "
                    "Category Manager review required before award."
                )
            else:
                parts.append(
                    "Market remains concentrated. Recommend supplier diversification plan."
                )
        elif label_after == "MODERATE":
            if crosses:
                parts.append(
                    "Segment moves from COMPETITIVE to MODERATE. Monitor in next review cycle."
                )
        else:
            parts.append("Concentration within competitive range. No action required.")

        if dep_flag:
            parts.append(
                f"{name} share reaches {share_after:.1f}% (>{MAX_SINGLE_SUPPLIER_SHARE}% threshold) — "
                f"single-supplier dependency flag triggered."
            )
        return " ".join(parts)

    # ─────────────────────────────────────────────────────────────────────────
    # PRINT REPORT
    # ─────────────────────────────────────────────────────────────────────────

    def print_report(self, top_n: int = 20) -> None:
        segs = sorted(
            self._segments.values(), key=lambda s: s.hhi, reverse=True
        )[:top_n]

        print("\n" + "═" * 80)
        print("SUPPLIER CONCENTRATION RISK REPORT")
        print(f"Metric: Herfindahl-Hirschman Index (HHI) | "
              f"Segments: {len(self._segments)}")
        print(f"Thresholds: <{HHI_COMPETITIVE} COMPETITIVE | "
              f"{HHI_COMPETITIVE}–{HHI_MODERATE} MODERATE | "
              f">{HHI_MODERATE} CONCENTRATED | 10000 MONOPOLY")
        print("═" * 80)
        print(f"{'Category / Region':<35}  {'HHI':>6}  {'Label':<13}  "
              f"{'Top supplier':<24}  {'Share':>6}  {'n_sup':>5}")
        print("─" * 80)

        for s in segs:
            flag = " ⚠" if s.dependency_flag or s.single_source_risk else ""
            print(
                f"  {s.category_l2[:20]:<20} / {s.region:<10}  "
                f"{s.hhi:>6.0f}  {s.hhi_label:<13}  "
                f"{s.top_supplier_name[:22]:<24}  "
                f"{s.top_supplier_share_pct:>5.1f}%  "
                f"{s.n_active_suppliers:>5}"
                f"{flag}"
            )

        n_concentrated = sum(1 for s in self._segments.values()
                             if s.hhi >= HHI_MODERATE)
        n_flagged      = sum(1 for s in self._segments.values()
                             if s.dependency_flag or s.single_source_risk)
        print("─" * 80)
        print(f"  ⚠ = dependency flag (top supplier >40%) or single-source risk")
        print(f"  Concentrated segments: {n_concentrated} / {len(self._segments)}")
        print(f"  Dependency flags:      {n_flagged}")
        print("═" * 80)

    # ─────────────────────────────────────────────────────────────────────────
    # INTERNAL: load and build
    # ─────────────────────────────────────────────────────────────────────────

    def _load_and_build(self) -> None:
        awards  = self._load_awards()
        merged  = self._load_merged()

        if awards.empty:
            print("[ConcentrationRiskMonitor] No awards data.")
            return

        # Only awarded=True rows with a value
        df = awards[awards["awarded"] == True].copy()
        if df.empty:
            return

        # Normalise total_value to EUR
        if "currency" not in df.columns:
            df["currency"] = "EUR"
        df["value_eur"] = df.apply(
            lambda r: _to_eur(float(r.get("total_value") or 0),
                               str(r.get("currency", "EUR"))),
            axis=1,
        )

        # Join region from merged_v2 via supplier_id + category_l2
        if not merged.empty and "region" in merged.columns:
            region_map = (
                merged[["supplier_id", "category_l2", "region"]]
                .drop_duplicates(subset=["supplier_id", "category_l2"])
            )
            df = df.merge(region_map, on=["supplier_id", "category_l2"], how="left")
        
        if "region" not in df.columns:
            df["region"] = "EU"   # fallback
        df["region"] = df["region"].fillna("EU")

        self._raw = df

        # Build per-segment concentration
        for (cat2, region), grp in df.groupby(["category_l2", "region"]):
            seg = self._build_segment(str(cat2), str(region), grp)
            self._segments[(str(cat2), str(region))] = seg

    def _build_segment(
        self, cat2: str, region: str, grp: pd.DataFrame
    ) -> SegmentConcentration:
        # Aggregate value per supplier
        by_sup = (
            grp.groupby(["supplier_id", "supplier_name"])["value_eur"]
            .sum()
            .reset_index()
            .sort_values("value_eur", ascending=False)
        )

        total_eur = float(by_sup["value_eur"].sum())
        if total_eur <= 0:
            total_eur = 1.0   # avoid division by zero

        by_sup["share_pct"] = by_sup["value_eur"] / total_eur * 100

        # HHI = Σ share_i²
        hhi = float((by_sup["share_pct"] ** 2).sum())

        top = by_sup.iloc[0]
        top3_share = float(by_sup["share_pct"].head(3).sum())

        supplier_shares = [
            {
                "supplier_id":   str(row["supplier_id"]),
                "supplier_name": str(row["supplier_name"]),
                "value_eur":     round(float(row["value_eur"]), 2),
                "share_pct":     round(float(row["share_pct"]), 2),
            }
            for _, row in by_sup.iterrows()
        ]

        dep_flag = float(top["share_pct"]) > MAX_SINGLE_SUPPLIER_SHARE

        return SegmentConcentration(
            category_l2=cat2,
            region=region,
            n_active_suppliers=len(by_sup),
            total_awarded_eur=round(total_eur, 2),
            hhi=round(hhi, 1),
            hhi_label=_hhi_label(hhi),
            top_supplier_id=str(top["supplier_id"]),
            top_supplier_name=str(top["supplier_name"]),
            top_supplier_share_pct=round(float(top["share_pct"]), 1),
            top_3_share_pct=round(top3_share, 1),
            dependency_flag=dep_flag,
            single_source_risk=(len(by_sup) == 1),
            supplier_shares=supplier_shares,
        )

    def _load_awards(self) -> pd.DataFrame:
        for p in [
            self.data_dir / "historical_awards.csv",
            self.data_dir / "../data/historical_awards.csv",
        ]:
            if p.exists():
                try:
                    df = pd.read_csv(p)
                    if "awarded" in df.columns:
                        df["awarded"] = (
                            df["awarded"].astype(str).str.strip().str.lower()
                            .isin(["true", "1", "yes"])
                        )
                    return df
                except Exception as e:
                    print(f"[ConcentrationRiskMonitor] Load error: {e}")
        return pd.DataFrame()

    def _load_merged(self) -> pd.DataFrame:
        for p in [
            self.data_dir / "merged_v2.csv",
            self.data_dir / "../data/merged_v2.csv",
        ]:
            if p.exists():
                try:
                    return pd.read_csv(p)[
                        ["supplier_id", "category_l2", "region"]
                    ].drop_duplicates()
                except Exception:
                    pass
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE INTEGRATION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

class HistoricalAnalytics:
    """
    Single object that wraps both modules.
    Instantiate once on pipeline startup; call per-request methods cheaply.

    In pipeline.py __init__:
        from historical_analytics import HistoricalAnalytics
        self.analytics = HistoricalAnalytics(data_dir=data_dir)

    In pipeline.py run():
        engine_output = self.analytics.attach(engine_output, working_request)
    """

    def __init__(self, data_dir: str | Path = "data"):
        self.data_dir     = Path(data_dir)
        self.cycle        = EscalationCycleAnalyzer(data_dir)
        self.concentration = ConcentrationRiskMonitor(data_dir)

    def attach(self, engine_output: dict, request: dict) -> dict:
        """
        Attach SLA prediction and concentration impact to the pipeline output.
        Call this after Layer 3 (calibrated scoring) and before Layer 4 (rationale).
        """
        out = engine_output

        # ── SLA prediction ──────────────────────────────────────────────────
        escalation_targets = list({
            e.get("escalate_to") or e.get("target", "")
            for e in out.get("escalations", [])
            if e.get("escalate_to") or e.get("target")
        })

        req_by = request.get("required_by_date")
        days_to_deadline = None
        if req_by:
            try:
                days_to_deadline = (
                    date.fromisoformat(str(req_by)) - date.today()
                ).days
            except Exception:
                pass

        sla = self.cycle.predict_sla(escalation_targets, days_to_deadline)
        out["sla_prediction"] = asdict(sla)
        out["escalation_cycle_insights"] = self._build_escalation_cycle_insights(
            out=out,
            request=request,
            days_to_deadline=days_to_deadline,
        )

        # ── Concentration impact ─────────────────────────────────────────────
        shortlist = out.get("supplier_shortlist", [])
        if shortlist:
            top          = shortlist[0]
            countries    = request.get("delivery_countries") or [
                request.get("country", "DE")
            ]
            region       = COUNTRY_TO_REGION.get(countries[0], "EU")
            cat2         = request.get("category_l2", "")
            budget       = float(request.get("budget_amount") or 0)
            currency     = request.get("currency", "EUR")
            value_eur    = _to_eur(budget, currency)

            impact = self.concentration.award_impact(
                supplier_id   = str(top.get("supplier_id", "")),
                supplier_name = str(top.get("supplier_name", "")),
                category_l2   = cat2,
                region        = region,
                award_value_eur = value_eur,
            )
            out["concentration_impact"] = asdict(impact)

            # Auto-escalate if concentration crosses into CONCENTRATED
            if impact.crosses_threshold and impact.label_after in ("CONCENTRATED", "MONOPOLY"):
                out.setdefault("escalations", []).append({
                    "rule": "ER-CON-001",
                    "trigger": (
                        f"Award to {top.get('supplier_name')} raises {cat2}/{region} "
                        f"HHI from {impact.hhi_before:.0f} to {impact.hhi_after:.0f} "
                        f"({impact.label_after}). {impact.recommendation}"
                    ),
                    "escalate_to": "Head of Category",
                    "blocking": False,
                    "source": "concentration_monitor",
                })

        return out

    def _build_escalation_cycle_insights(
        self,
        out: dict,
        request: dict,
        days_to_deadline: int | None,
    ) -> dict[str, Any]:
        """
        Build urgency-scored feasibility insights for each escalation target.
        This is a separate section from raw escalations to help human reviewers
        decide whether the normal process can still meet required_by_date.
        """
        business_unit = request.get("business_unit")
        escalations = out.get("escalations", []) or []
        targets: list[str] = []
        for e in escalations:
            target = str(e.get("escalate_to", "")).strip()
            if target and target not in targets:
                targets.append(target)

        if not targets:
            return {
                "summary": "No escalation targets triggered; cycle-feasibility analysis not required.",
                "days_to_deadline": days_to_deadline,
                "insights": [],
            }

        insights = []
        for target in targets:
            stats = self.cycle.cycle_stats_for_target(target, business_unit=business_unit)
            mean_days = float(stats["mean_days"])
            median_days = float(stats["median_days"])
            sample_n = int(stats["n"])
            scoped = bool(stats["scoped_to_business_unit"])

            if days_to_deadline is None:
                urgency = "unknown"
            elif days_to_deadline < median_days:
                urgency = "critical"
            elif days_to_deadline < mean_days + 2:
                urgency = "tight"
            else:
                urgency = "ok"

            dataset_scope = (
                f"in {business_unit}" if (business_unit and scoped) else "in comparable historical requests"
            )
            headline = (
                f"This request needs {target} approval. "
                f"Historical {target} cycle averages {mean_days:.1f} days {dataset_scope}."
            )
            if days_to_deadline is not None:
                headline += f" Delivery required in {days_to_deadline} days."

            if urgency in ("critical", "tight"):
                parallel_partner = (
                    "Head of Strategic Sourcing"
                    if target != "Head of Strategic Sourcing"
                    else "Procurement Manager"
                )
                action = (
                    f"Recommended action: compress to parallel escalation - "
                    f"{target} + {parallel_partner} notified simultaneously, "
                    "auto-24h reminder."
                )
            elif urgency == "ok":
                action = (
                    "Recommended action: run standard escalation flow, "
                    "with reminder cadence every 48h."
                )
            else:
                action = (
                    "Recommended action: required_by_date missing or invalid; "
                    "capture deadline to assess cycle feasibility."
                )

            insights.append({
                "target": target,
                "urgency": urgency,
                "historical_mean_days": mean_days,
                "historical_median_days": median_days,
                "historical_sample_size": sample_n,
                "scoped_to_business_unit": scoped,
                "days_to_deadline": days_to_deadline,
                "insight": headline,
                "recommended_action": action,
            })

        return {
            "summary": (
                "Escalation feasibility assessed using historical approval-cycle durations "
                "versus required delivery date."
            ),
            "days_to_deadline": days_to_deadline,
            "insights": insights,
        }


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT  — standalone reports
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    from pathlib import Path

    base     = Path(__file__).parent
    data_dir = base / "data"
    if not data_dir.exists():
        data_dir = base / "../data"

    analytics = HistoricalAnalytics(data_dir=data_dir)

    # ── Report 1: Escalation cycle times ────────────────────────────────────
    analytics.cycle.print_report()

    # ── Report 2: Concentration risk ────────────────────────────────────────
    analytics.concentration.print_report()

    # ── Demo: SLA prediction for a multi-escalation request ─────────────────
    print("\n── SLA Prediction Demo ──")
    sla = analytics.cycle.predict_sla(
        escalation_targets=["Procurement Manager", "Head of Strategic Sourcing"],
        days_to_deadline=8,
    )
    print(f"  Worst-case target : {sla.worst_case_target}")
    print(f"  Expected days     : {sla.expected_days:.1f}d (median) / {sla.p90_days:.1f}d (p90)")
    print(f"  SLA status        : {sla.sla_status}")
    print(f"  Detail            : {sla.sla_detail}")
    print(f"  Parallel routing  : {sla.parallel_routing_advised}")

    # ── Demo: Concentration impact for a hypothetical award ──────────────────
    print("\n── Concentration Impact Demo ──")
    impact = analytics.concentration.award_impact(
        supplier_id     = "SUP-0012",
        supplier_name   = "TechCore Solutions",
        category_l2     = "Laptops",
        region          = "EU",
        award_value_eur = 395_200.0,
    )
    print(f"  Segment     : {impact.category_l2} / {impact.region}")
    print(f"  HHI before  : {impact.hhi_before:.0f} ({impact.label_before})")
    print(f"  HHI after   : {impact.hhi_after:.0f} ({impact.label_after})")
    print(f"  Share after : {impact.share_after_pct:.1f}%")
    print(f"  Flag        : {'⚠ ' if impact.dependency_flag_new else '✓ '}"
          f"{'DEPENDENCY FLAG' if impact.dependency_flag_new else 'Within limits'}")
    print(f"  Action      : {impact.recommendation}")

    # ── Save full portfolio to JSON ──────────────────────────────────────────
    out = {
        "escalation_cycle_profiles": {
            k: asdict(v)
            for k, v in analytics.cycle.profiles().items()
        },
        "concentration_segments": [
            asdict(s) for s in analytics.concentration.segments()
        ],
    }
    out_path = base / "historical_analytics_report.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nFull report saved → {out_path}")
