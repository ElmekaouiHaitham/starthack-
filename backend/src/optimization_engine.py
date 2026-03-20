"""
optimization_engine.py  —  ChainIQ START Hack 2026
===================================================
Two modules that add commercial optimization on top of the existing pipeline:

  1. DemandAggregator   — finds bundling opportunities across all 304 requests
  2. NegotiationAdvisor — finds parameter tweaks that improve a single decision

Both modules read directly from the same data files the rule engine uses
(merged_v2.csv for pricing tiers, requests.json for cross-request analysis)
and produce structured suggestions the pipeline can embed in its output.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MODULE 1: DemandAggregator
━━━━━━━━━━━━━━━━━━━━━━━━━━

HOW PRICING TIERS WORK IN THIS DATASET
Hardware (e.g. Laptops):   1–99 | 100–499 | 500–1999 | 2000+
Services (day_rate etc.):  1–9  | 10–49   | 50–199   | 200+

A bundled order jumps a tier when sum(quantities) crosses min_quantity of the
next tier. The saving is:
  Δsaving = (unit_price_current_tier - unit_price_next_tier) × total_quantity

The aggregator:
  1. Loads all pending requests (those not yet in historical_awards.csv)
  2. Groups by (category_l1, category_l2, delivery_region, currency)
     within a configurable rolling time window (default: 30 days)
  3. For each group with ≥ 2 requests:
     a. Finds the supplier shortlisted by the majority of requests
     b. Looks up what tier combined_quantity would hit in merged_v2.csv
     c. Compares: Σ(individual tier prices) vs bundled tier price
     d. If saving > threshold: emit a BundleOpportunity

Split-order detection (compliance guard):
  Requests in the same window whose individual quantities are each just below
  a tier boundary but whose sum exceeds it are flagged as POTENTIAL_SPLIT.
  This catches both genuine bundle opportunities AND policy-evasion attempts.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MODULE 2: NegotiationAdvisor
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For a single processed request it answers: "what's the minimum change to
the request parameters that would materially improve the outcome?"

It checks six levers, in priority order:
  1. lead_time_extension   — relax required_by_date by N days →
                             supplier switches from expedited to standard pricing
  2. budget_increase       — raise budget_amount by X% →
                             score gap closes / new supplier becomes preferred
  3. quantity_reduction    — reduce quantity by N units →
                             drop to cheaper pricing tier with same supplier
  4. quantity_increase     — increase quantity slightly →
                             jump to next tier with lower unit price
  5. esg_waiver            — remove esg_requirement=True →
                             N additional suppliers become eligible
  6. country_split         — deliver to subset of countries per supplier →
                             geo-restriction lifted for a specific supplier

Each suggestion has:
  type            — one of the six above
  description     — plain English: "If you allow 3 more days lead time..."
  parameter_change — exactly what to change: {"required_by_date": "2026-04-18"}
  saving_amount    — EUR / CHF / USD saving vs current recommendation
  saving_pct       — as % of current contract value
  new_supplier     — which supplier benefits (or None = same supplier, better price)
  confidence       — "HIGH" | "MEDIUM" | "LOW" based on data certainty

INTEGRATION
───────────
  # After pipeline.run() — add to any single request output:
  from optimization_engine import NegotiationAdvisor, DemandAggregator

  advisor   = NegotiationAdvisor(data_dir="data/")
  result["negotiation_levers"] = advisor.advise(result, request)

  # Once per batch run — cross-request analysis:
  aggregator = DemandAggregator(data_dir="data/")
  bundles    = aggregator.find_opportunities(all_requests, awarded_request_ids)
  # bundles is a list of BundleOpportunity — attach to the batch summary
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS  (match rule_engine_v3.py)
# ══════════════════════════════════════════════════════════════════════════════

FX_TO_EUR: dict[str, float] = {
    "EUR": 1.0,
    "CHF": 1.04,
    "USD": 0.92,
}

COUNTRY_TO_REGION: dict[str, str] = {
    "DE": "EU", "FR": "EU", "NL": "EU", "BE": "EU", "AT": "EU",
    "IT": "EU", "ES": "EU", "PL": "EU", "UK": "EU",
    "CH": "CH",
    "US": "Americas", "CA": "Americas", "BR": "Americas", "MX": "Americas",
    "SG": "APAC", "AU": "APAC", "IN": "APAC", "JP": "APAC",
    "UAE": "MEA", "ZA": "MEA",
}

BUNDLE_WINDOW_DAYS   = 30     # requests within this window are candidates
MIN_SAVING_EUR       = 50     # relaxed for demo
MIN_SAVING_PCT       = 0.1    # relaxed for demo
SPLIT_THRESHOLD_PCT  = 0.90   # quantity within 90% of a tier boundary = suspect split


def _to_eur(amount: float, currency: str) -> float:
    return amount * FX_TO_EUR.get(currency, 1.0)


def _from_eur(amount_eur: float, currency: str) -> float:
    rate = FX_TO_EUR.get(currency, 1.0)
    return amount_eur / rate if rate else amount_eur


# ══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class BundleOpportunity:
    # Identification
    opportunity_id:    str
    category_l1:       str
    category_l2:       str
    region:            str

    # Constituent requests
    request_ids:       list[str]
    request_count:     int
    individual_quantities: list[float]

    # Quantities
    combined_quantity: float
    individual_total_cost_eur: float   # sum of individual best-tier prices

    # Bundled economics
    bundled_unit_price_eur:   float
    bundled_total_cost_eur:   float
    saving_eur:               float
    saving_pct:               float

    # Tier info
    individual_tier_label:    str    # e.g. "Tier 2 (100–499 units)"
    bundled_tier_label:       str    # e.g. "Tier 3 (500–1999 units)"
    tier_boundary_crossed:    int    # the min_quantity of the next tier

    # Best supplier for the bundle
    recommended_supplier_id:   str
    recommended_supplier_name: str

    # Compliance flag
    split_detection_flag:     bool   # True = pattern looks like split purchasing
    split_detail:             str

    # Human-readable
    summary: str


@dataclass
class NegotiationLever:
    type:             str     # lead_time_extension | budget_increase | etc.
    description:      str     # plain English suggestion
    parameter_change: dict    # machine-readable: what to actually change
    saving_amount:    float   # in request currency
    saving_pct:       float   # % of current contract value
    new_supplier:     str | None
    original_supplier: str | None
    confidence:       str     # HIGH | MEDIUM | LOW
    detail:           str     # brief technical explanation for audit


# ══════════════════════════════════════════════════════════════════════════════
# 1.  DEMAND AGGREGATOR
# ══════════════════════════════════════════════════════════════════════════════

class DemandAggregator:
    """
    Cross-request bundling analysis.

    Loads all requests.json, finds groups that could be bundled to unlock
    a better pricing tier, and flags potential split-purchasing.

    Usage:
        agg     = DemandAggregator(data_dir="data/")
        bundles = agg.find_opportunities(all_requests, awarded_ids=set())
        summary = agg.summary_report(bundles)
    """

    def __init__(self, data_dir: str | Path = "data"):
        self.data_dir = Path(data_dir)
        self._pricing = self._load_pricing()

    # ─────────────────────────────────────────────────────────────────────────

    def find_opportunities(
        self,
        requests: list[dict],
        awarded_ids: set[str] | None = None,
        window_days: int = BUNDLE_WINDOW_DAYS,
    ) -> list[BundleOpportunity]:
        """
        Main entry point. Pass all 304 requests and the set of request_ids
        that already have historical awards (those are done — skip them).

        Returns list of BundleOpportunity, sorted by saving_eur descending.
        """
        awarded_ids = awarded_ids or set()

        # Filter to pending requests with a known quantity
        pending = [
            r for r in requests
            if r.get("request_id") not in awarded_ids
            and r.get("quantity") is not None
            and r.get("category_l2") is not None
        ]

        opportunities: list[BundleOpportunity] = []

        # Group by (category_l1, category_l2, primary_region)
        groups: dict[tuple, list[dict]] = {}
        for req in pending:
            countries = req.get("delivery_countries") or [req.get("country", "DE")]
            region    = COUNTRY_TO_REGION.get(countries[0], "EU")
            key       = (
                req.get("category_l1", ""),
                req.get("category_l2", ""),
                region,
            )
            groups.setdefault(key, []).append(req)

        # Within each group, find time-window clusters
        for (cat1, cat2, region), group_reqs in groups.items():
            if len(group_reqs) < 2:
                continue

            clusters = self._time_cluster(group_reqs, window_days)

            for cluster in clusters:
                if len(cluster) < 2:
                    continue
                opp = self._evaluate_bundle(cluster, cat1, cat2, region)
                if opp and opp.saving_eur >= MIN_SAVING_EUR:
                    opportunities.append(opp)

        opportunities.sort(key=lambda o: o.saving_eur, reverse=True)
        return opportunities

    # ─────────────────────────────────────────────────────────────────────────

    def _time_cluster(
        self, reqs: list[dict], window_days: int
    ) -> list[list[dict]]:
        """
        Simple sliding-window cluster: sort by created_at, then group
        requests within window_days of the earliest in the cluster.
        """
        def parse_date(r: dict) -> date:
            s = r.get("created_at", "2026-01-01")
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
            except Exception:
                return date(2026, 1, 1)

        sorted_reqs = sorted(reqs, key=parse_date)
        clusters    = []
        used        = set()

        for i, anchor in enumerate(sorted_reqs):
            if i in used:
                continue
            cluster = [anchor]
            anchor_date = parse_date(anchor)
            for j, other in enumerate(sorted_reqs):
                if j == i or j in used:
                    continue
                if abs((parse_date(other) - anchor_date).days) <= window_days:
                    cluster.append(other)
                    used.add(j)
            used.add(i)
            if len(cluster) >= 2:
                clusters.append(cluster)

        return clusters

    # ─────────────────────────────────────────────────────────────────────────

    def _evaluate_bundle(
        self,
        cluster: list[dict],
        cat1: str,
        cat2: str,
        region: str,
    ) -> BundleOpportunity | None:
        """
        For a cluster of requests in the same category/region:
          1. Compute combined quantity
          2. Find the best supplier with pricing for this category/region
          3. Compare individual tier cost vs bundled tier cost
          4. Return BundleOpportunity if saving is material
        """
        quantities   = [float(r.get("quantity", 0)) for r in cluster]
        total_qty    = sum(quantities)
        currencies   = [r.get("currency", "EUR") for r in cluster]
        # Use most common currency for display
        display_ccy  = max(set(currencies), key=currencies.count)

        # Get all pricing rows for this category/region
        tiers = self._pricing[
            (self._pricing["category_l1"] == cat1) &
            (self._pricing["category_l2"] == cat2) &
            (self._pricing["region"]      == region)
        ].copy()

        if tiers.empty:
            return None

        # Find the supplier with best (lowest) unit price at the bundled quantity
        # and who has a tier that covers the bundled quantity
        bundled_rows = tiers[
            (tiers["min_quantity"] <= total_qty) &
            (tiers["max_quantity"] >= total_qty)
        ]
        if bundled_rows.empty:
            # Total quantity exceeds all tiers — use the highest tier
            bundled_rows = tiers[tiers["max_quantity"] == tiers["max_quantity"].max()]
        if bundled_rows.empty:
            return None

        best_bundled = bundled_rows.loc[bundled_rows["unit_price"].idxmin()]
        sup_id       = best_bundled["supplier_id"]
        sup_name     = best_bundled.get("supplier_name", str(sup_id))

        bundled_unit_eur   = _to_eur(float(best_bundled["unit_price"]),
                                      str(best_bundled["currency"]))
        bundled_total_eur  = bundled_unit_eur * total_qty

        # Individual costs: for each request, find its own tier price
        # from the SAME supplier to ensure apples-to-apples comparison
        sup_tiers = tiers[tiers["supplier_id"] == sup_id].sort_values("min_quantity")

        individual_total_eur = 0.0
        individual_tier_labels = []
        for qty in quantities:
            row = sup_tiers[
                (sup_tiers["min_quantity"] <= qty) &
                (sup_tiers["max_quantity"] >= qty)
            ]
            if row.empty:
                # Quantity below MOQ or above max — use closest tier
                row = sup_tiers
            if row.empty:
                continue
            best_row = row.loc[row["unit_price"].idxmin()]
            individual_total_eur += _to_eur(float(best_row["unit_price"]),
                                             str(best_row["currency"])) * qty
            label = (f"Tier {best_row['min_quantity']:.0f}–"
                     f"{best_row['max_quantity']:.0f}")
            if label not in individual_tier_labels:
                individual_tier_labels.append(label)

        saving_eur = individual_total_eur - bundled_total_eur
        if saving_eur <= 0:
            return None

        saving_pct = (saving_eur / individual_total_eur * 100) if individual_total_eur > 0 else 0

        if saving_pct < MIN_SAVING_PCT:
            return None

        # Bundled tier label
        bundled_label = (f"Tier {best_bundled['min_quantity']:.0f}–"
                         f"{best_bundled['max_quantity']:.0f}")

        # Tier boundary crossed
        tier_boundary = int(best_bundled["min_quantity"])

        # Split detection: are individual quantities just below a tier boundary?
        split_flag, split_detail = self._detect_split(
            quantities, sup_tiers, total_qty
        )

        # Human summary
        req_ids = [r.get("request_id", "?") for r in cluster]
        saving_display = _from_eur(saving_eur, display_ccy)
        summary = (
            f"Bundling {len(cluster)} {cat2} requests "
            f"({', '.join(req_ids[:3])}{'...' if len(req_ids)>3 else ''}) "
            f"combines {total_qty:.0f} units, crossing into {bundled_label} "
            f"pricing with {sup_name}. "
            f"Estimated saving: {saving_display:,.0f} {display_ccy} "
            f"({saving_pct:.1f}% of combined value)."
        )

        opp_id = f"BUNDLE-{cat2[:3].upper()}-{region}-{''.join(r[:6] for r in req_ids[:2])}"

        return BundleOpportunity(
            opportunity_id=opp_id,
            category_l1=cat1,
            category_l2=cat2,
            region=region,
            request_ids=req_ids,
            request_count=len(cluster),
            individual_quantities=quantities,
            combined_quantity=total_qty,
            individual_total_cost_eur=round(individual_total_eur, 2),
            bundled_unit_price_eur=round(bundled_unit_eur, 4),
            bundled_total_cost_eur=round(bundled_total_eur, 2),
            saving_eur=round(saving_eur, 2),
            saving_pct=round(saving_pct, 2),
            individual_tier_label=" / ".join(individual_tier_labels) or "Tier 1",
            bundled_tier_label=bundled_label,
            tier_boundary_crossed=tier_boundary,
            recommended_supplier_id=str(sup_id),
            recommended_supplier_name=str(sup_name),
            split_detection_flag=split_flag,
            split_detail=split_detail,
            summary=summary,
        )

    # ─────────────────────────────────────────────────────────────────────────

    def _detect_split(
        self,
        quantities: list[float],
        sup_tiers: pd.DataFrame,
        total_qty: float,
    ) -> tuple[bool, str]:
        """
        Flags when individual quantities are suspiciously just below a tier
        boundary — classic split-purchasing pattern.

        Condition: at least 2 requests individually fall within
        SPLIT_THRESHOLD_PCT of a tier's min_quantity (i.e., just below it),
        but their combined quantity crosses that boundary.
        """
        if sup_tiers.empty:
            return False, ""

        boundaries = sup_tiers["min_quantity"].sort_values().unique()
        suspicious = []

        for boundary in boundaries:
            if boundary <= 1:
                continue
            lower = boundary * SPLIT_THRESHOLD_PCT
            near_below = [q for q in quantities if lower <= q < boundary]
            if len(near_below) >= 2 and total_qty >= boundary:
                suspicious.append(
                    f"{len(near_below)} requests each just below "
                    f"{boundary:.0f}-unit tier boundary "
                    f"(combined: {total_qty:.0f} units)"
                )

        if suspicious:
            return True, (
                "POTENTIAL SPLIT PURCHASING DETECTED: " + "; ".join(suspicious) +
                ". Refer to procurement policy on order splitting."
            )
        return False, ""

    # ─────────────────────────────────────────────────────────────────────────

    def summary_report(self, opportunities: list[BundleOpportunity]) -> str:
        """Print a ranked summary of all bundle opportunities."""
        if not opportunities:
            return "No bundle opportunities found above threshold."

        total_saving = sum(o.saving_eur for o in opportunities)
        lines = [
            "=" * 72,
            f"DEMAND AGGREGATION REPORT — {len(opportunities)} opportunities",
            f"Total addressable saving: EUR {total_saving:,.0f}",
            "=" * 72,
        ]
        for i, o in enumerate(opportunities, 1):
            split_tag = " ⚠ SPLIT FLAG" if o.split_detection_flag else ""
            lines.append(
                f"\n[{i}] {o.category_l2} / {o.region}{split_tag}"
                f"\n    Requests : {', '.join(o.request_ids[:4])}"
                f"{'...' if o.request_count > 4 else ''}"
                f"\n    Quantities: {[f'{q:.0f}' for q in o.individual_quantities]}"
                f"  →  combined {o.combined_quantity:.0f} units"
                f"\n    Tier jump : {o.individual_tier_label} → {o.bundled_tier_label}"
                f"\n    Supplier  : {o.recommended_supplier_name}"
                f"\n    Saving    : EUR {o.saving_eur:,.0f}  ({o.saving_pct:.1f}%)"
            )
            if o.split_detection_flag:
                lines.append(f"    ⚠ {o.split_detail}")
        lines.append("\n" + "=" * 72)
        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────────────────

    def _load_pricing(self) -> pd.DataFrame:
        path = self.data_dir / "merged_v2.csv"
        if not path.exists():
            path = self.data_dir / "../data/merged_v2.csv"
        if not path.exists():
            # Try pricing.csv directly
            for p in [self.data_dir / "pricing.csv",
                      self.data_dir / "../data/pricing.csv"]:
                if p.exists():
                    path = p
                    break
        try:
            df = pd.read_csv(path)
            # Ensure required columns exist
            for col in ["supplier_id", "category_l1", "category_l2",
                        "region", "min_quantity", "max_quantity", "unit_price", "currency"]:
                if col not in df.columns:
                    df[col] = None
            return df
        except Exception as e:
            print(f"[DemandAggregator] Warning: could not load pricing data: {e}")
            return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# 2.  NEGOTIATION ADVISOR
# ══════════════════════════════════════════════════════════════════════════════

class NegotiationAdvisor:
    """
    Single-request parameter optimization.

    Given a processed pipeline output and the original request dict, finds
    the minimum parameter change that materially improves the outcome.

    Usage:
        advisor = NegotiationAdvisor(data_dir="data/")
        levers  = advisor.advise(engine_output, request)
        # levers is a list of NegotiationLever, sorted by saving_pct descending
        # Attach to the pipeline output:
        engine_output["negotiation_levers"] = [asdict(l) for l in levers]
    """

    def __init__(self, data_dir: str | Path = "data"):
        self.data_dir = Path(data_dir)
        self._pricing = self._load_pricing()

    # ─────────────────────────────────────────────────────────────────────────

    def advise(
        self,
        engine_output: dict,
        request: dict,
    ) -> list[NegotiationLever]:
        """
        Run all six levers and return non-trivial suggestions sorted by saving.
        """
        shortlist  = engine_output.get("supplier_shortlist", [])
        if not shortlist:
            return []

        top        = shortlist[0]                    # current recommended supplier
        runner_up  = shortlist[1] if len(shortlist) > 1 else None
        currency   = request.get("currency", "EUR")
        contract   = float(top.get("total_price_in_req_currency",
                                   request.get("budget_amount", 0) or 0))

        levers: list[NegotiationLever] = []

        levers += self._lever_lead_time(request, shortlist, top, currency, contract)
        levers += self._lever_budget(request, shortlist, top, currency, contract)
        levers += self._lever_quantity_down(request, top, currency, contract)
        levers += self._lever_quantity_up(request, top, currency, contract)
        levers += self._lever_esg_waiver(request, engine_output, top, currency, contract)
        levers += self._lever_country_split(request, engine_output, top, currency, contract)

        # Filter trivial suggestions and sort
        meaningful = [
            l for l in levers
            if l.saving_pct >= 0.5 or l.type == "esg_waiver"
        ]
        meaningful.sort(key=lambda l: l.saving_pct, reverse=True)
        return meaningful[:6]   # top 6 suggestions max

    # ─────────────────────────────────────────────────────────────────────────
    # LEVER 1: Lead-time extension
    # ─────────────────────────────────────────────────────────────────────────

    def _lever_lead_time(
        self,
        request: dict,
        shortlist: list[dict],
        top: dict,
        currency: str,
        contract: float,
    ) -> list[NegotiationLever]:
        """
        Check if the top supplier (or a runner-up) is using expedited pricing.
        If so, compute how many extra days would allow standard pricing.
        Also check: would extending the deadline unlock a restricted runner-up?
        """
        levers = []
        req_by_str = request.get("required_by_date")
        if not req_by_str:
            return levers

        try:
            req_by = date.fromisoformat(req_by_str)
        except Exception:
            return levers

        # Case A: top supplier is on expedited pricing
        std_lead  = top.get("lead_time_days")
        exp_lead  = top.get("expedited_lead_time_days")
        exp_price = top.get("expedited_unit_price")
        std_price = top.get("unit_price")
        qty       = float(request.get("quantity") or 0)

        if (std_lead and exp_lead and exp_price and std_price
                and std_lead > exp_lead and qty > 0):
            # Check if they're on expedited (i.e. required_by < std_lead days from now)
            days_available = (req_by - date.today()).days
            if days_available < std_lead:
                days_needed = std_lead - days_available
                saving_per_unit_eur = _to_eur(
                    float(exp_price) - float(std_price),
                    str(top.get("pricing_currency", currency))
                )
                saving_eur   = saving_per_unit_eur * qty
                saving_local = _from_eur(saving_eur, currency)
                saving_pct   = (saving_local / contract * 100) if contract > 0 else 0

                if saving_eur > 100:
                    new_date = req_by + timedelta(days=days_needed)
                    levers.append(NegotiationLever(
                        type="lead_time_extension",
                        description=(
                            f"Extending the delivery deadline by {days_needed} day"
                            f"{'s' if days_needed != 1 else ''} "
                            f"(to {new_date.isoformat()}) allows {top['supplier_name']} "
                            f"to use standard shipping instead of expedited, "
                            f"saving {saving_local:,.0f} {currency} "
                            f"({saving_pct:.1f}% of contract value)."
                        ),
                        parameter_change={"required_by_date": new_date.isoformat()},
                        saving_amount=round(saving_local, 2),
                        saving_pct=round(saving_pct, 2),
                        new_supplier=None,
                        original_supplier=top.get("supplier_name"),
                        confidence="HIGH",
                        detail=(
                            f"Standard lead time: {std_lead}d. "
                            f"Expedited lead time: {exp_lead}d. "
                            f"Unit price delta: {saving_per_unit_eur:.2f} EUR/unit × {qty:.0f} units."
                        ),
                    ))

        # Case B: runner-up has shorter standard lead time but lost on score
        # (would extending deadline help a better runner-up win with standard pricing?)
        for runner in shortlist[1:3]:
            r_std_lead = runner.get("lead_time_days")
            if not r_std_lead:
                continue
            days_available = (req_by - date.today()).days
            if days_available >= r_std_lead:
                continue   # runner already qualifies under current deadline

            # Runner would qualify with N more days — but is its price better?
            r_total     = float(runner.get("total_price_in_req_currency", 0))
            top_total   = float(top.get("total_price_in_req_currency", 0))
            if r_total >= top_total:
                continue   # runner is not cheaper even in standard mode

            days_extra  = r_std_lead - days_available
            saving_local = top_total - r_total
            saving_pct   = (saving_local / contract * 100) if contract > 0 else 0
            new_date     = req_by + timedelta(days=days_extra)

            if saving_local > 50 and days_extra <= 7:
                levers.append(NegotiationLever(
                    type="lead_time_extension",
                    description=(
                        f"Extending the deadline by {days_extra} day"
                        f"{'s' if days_extra != 1 else ''} "
                        f"(to {new_date.isoformat()}) makes {runner['supplier_name']} "
                        f"viable under standard delivery, saving "
                        f"{saving_local:,.0f} {currency} "
                        f"({saving_pct:.1f}%) vs the current recommendation."
                    ),
                    parameter_change={"required_by_date": new_date.isoformat()},
                    saving_amount=round(saving_local, 2),
                    saving_pct=round(saving_pct, 2),
                    new_supplier=runner.get("supplier_name"),
                    original_supplier=top.get("supplier_name"),
                    confidence="MEDIUM",
                    detail=(
                        f"{runner['supplier_name']} standard lead time: {r_std_lead}d. "
                        f"Days currently available: {days_available}. "
                        f"Gap: {days_extra}d."
                    ),
                ))

        return levers

    # ─────────────────────────────────────────────────────────────────────────
    # LEVER 2: Budget increase → better supplier becomes competitive
    # ─────────────────────────────────────────────────────────────────────────

    def _lever_budget(
        self,
        request: dict,
        shortlist: list[dict],
        top: dict,
        currency: str,
        contract: float,
    ) -> list[NegotiationLever]:
        """
        Checks: is there a runner-up with significantly better quality/risk/ESG
        that lost primarily because it's more expensive? If the budget increase
        to reach it is small (< 10%), suggest it.
        """
        levers = []
        budget = float(request.get("budget_amount") or 0)
        if budget <= 0:
            return levers

        for runner in shortlist[1:3]:
            r_total   = float(runner.get("total_price_in_req_currency", 0))
            top_total = float(top.get("total_price_in_req_currency", 0))
            if r_total <= top_total:
                continue   # runner is already cheaper — budget isn't the issue

            delta        = r_total - top_total       # extra cost vs current
            delta_pct    = (delta / budget * 100) if budget > 0 else 99
            if delta_pct > 10:
                continue   # too expensive — not a practical suggestion

            # Only worth suggesting if runner has meaningfully better scores
            quality_gain = (float(runner.get("quality_score", 0)) -
                            float(top.get("quality_score", 0)))
            risk_gain    = (float(top.get("risk_score", 0)) -
                            float(runner.get("risk_score", 0)))   # lower = better
            esg_gain     = (float(runner.get("esg_score", 0)) -
                            float(top.get("esg_score", 0)))

            if quality_gain + risk_gain + esg_gain < 5:
                continue   # marginal improvement not worth extra spend

            new_budget = budget + delta
            confidence = "HIGH" if delta_pct < 3 else ("MEDIUM" if delta_pct < 7 else "LOW")

            gains_desc = []
            if quality_gain >= 3:
                gains_desc.append(f"quality +{quality_gain:.0f}pts")
            if risk_gain >= 3:
                gains_desc.append(f"risk score -{risk_gain:.0f}pts (lower is better)")
            if esg_gain >= 3:
                gains_desc.append(f"ESG +{esg_gain:.0f}pts")

            levers.append(NegotiationLever(
                type="budget_increase",
                description=(
                    f"Increasing the budget by {delta:,.0f} {currency} "
                    f"({delta_pct:.1f}%) makes {runner['supplier_name']} the "
                    f"optimal choice, improving: {', '.join(gains_desc) or 'overall score'}."
                ),
                parameter_change={"budget_amount": round(new_budget, 2)},
                saving_amount=-round(delta, 2),   # negative = extra spend
                saving_pct=-round(delta_pct, 2),
                new_supplier=runner.get("supplier_name"),
                original_supplier=top.get("supplier_name"),
                confidence=confidence,
                detail=(
                    f"Current top: {top['supplier_name']} @ {top_total:,.0f} {currency}. "
                    f"Alternative: {runner['supplier_name']} @ {r_total:,.0f} {currency}. "
                    f"Delta: {delta:,.0f} {currency} ({delta_pct:.1f}% over budget)."
                ),
            ))

        return levers

    # ─────────────────────────────────────────────────────────────────────────
    # LEVER 3: Quantity reduction → cheaper pricing tier
    # ─────────────────────────────────────────────────────────────────────────

    def _lever_quantity_down(
        self,
        request: dict,
        top: dict,
        currency: str,
        contract: float,
    ) -> list[NegotiationLever]:
        """
        If the current quantity is just above a tier boundary, check if
        reducing by a small amount drops to a cheaper tier.
        (Only valid when some quantity can be deferred to a later order.)
        """
        levers   = []
        qty      = float(request.get("quantity") or 0)
        if qty <= 1:
            return levers

        sup_id  = top.get("supplier_id")
        cat1    = request.get("category_l1", "")
        cat2    = request.get("category_l2", "")
        countries = request.get("delivery_countries") or [request.get("country", "DE")]
        region  = COUNTRY_TO_REGION.get(countries[0], "EU")

        sup_tiers = self._pricing[
            (self._pricing["supplier_id"] == sup_id) &
            (self._pricing["category_l1"] == cat1) &
            (self._pricing["category_l2"] == cat2) &
            (self._pricing["region"]      == region)
        ].sort_values("min_quantity")

        if sup_tiers.empty:
            return levers

        # Current tier
        current_rows = sup_tiers[
            (sup_tiers["min_quantity"] <= qty) & (sup_tiers["max_quantity"] >= qty)
        ]
        if current_rows.empty:
            return levers
        current_unit  = float(current_rows.iloc[0]["unit_price"])
        current_tier_min = float(current_rows.iloc[0]["min_quantity"])
        price_ccy     = str(current_rows.iloc[0]["currency"])

        # Is there a cheaper tier just below?
        lower_tiers = sup_tiers[sup_tiers["max_quantity"] < current_tier_min]
        if lower_tiers.empty:
            return levers

        lower_tier    = lower_tiers.iloc[-1]   # the tier just below current
        lower_unit    = float(lower_tier["unit_price"])
        lower_max_qty = float(lower_tier["max_quantity"])

        if lower_unit >= current_unit:
            return levers   # lower tier is not cheaper — unusual but possible

        # How many units to drop?
        units_to_drop = qty - lower_max_qty
        if units_to_drop <= 0 or units_to_drop > qty * 0.50:  # 50% for demo
            return levers   # dropping > 25% of order is not practical

        # Cost of lower tier for reduced quantity
        new_total_eur = _to_eur(lower_unit, price_ccy) * lower_max_qty
        old_total_eur = _to_eur(current_unit, price_ccy) * qty
        saving_eur    = old_total_eur - new_total_eur
        saving_local  = _from_eur(saving_eur, currency)
        saving_pct    = (saving_local / contract * 100) if contract > 0 else 0

        if saving_eur < 50:  # 50 for demo
            return levers

        levers.append(NegotiationLever(
            type="quantity_reduction",
            description=(
                f"Reducing the order by {units_to_drop:.0f} units "
                f"(from {qty:.0f} to {lower_max_qty:.0f}) drops into a "
                f"cheaper pricing tier with {top['supplier_name']}, "
                f"saving {saving_local:,.0f} {currency} ({saving_pct:.1f}%). "
                f"The remaining {units_to_drop:.0f} units can be deferred "
                f"to a follow-on order."
            ),
            parameter_change={"quantity": lower_max_qty},
            saving_amount=round(saving_local, 2),
            saving_pct=round(saving_pct, 2),
            new_supplier=None,
            original_supplier=top.get("supplier_name"),
            confidence="MEDIUM",
            detail=(
                f"Current tier unit price: {current_unit} {price_ccy}. "
                f"Lower tier unit price: {lower_unit} {price_ccy}. "
                f"Tier boundary: {current_tier_min:.0f} units."
            ),
        ))
        return levers

    # ─────────────────────────────────────────────────────────────────────────
    # LEVER 4: Quantity increase → jump to next tier, lower unit price
    # ─────────────────────────────────────────────────────────────────────────

    def _lever_quantity_up(
        self,
        request: dict,
        top: dict,
        currency: str,
        contract: float,
    ) -> list[NegotiationLever]:
        """
        If the current quantity is just below the next pricing tier,
        suggest increasing by a small amount to unlock the lower unit price.
        """
        levers   = []
        qty      = float(request.get("quantity") or 0)
        if qty <= 0:
            return levers

        sup_id   = top.get("supplier_id")
        cat1     = request.get("category_l1", "")
        cat2     = request.get("category_l2", "")
        countries = request.get("delivery_countries") or [request.get("country", "DE")]
        region   = COUNTRY_TO_REGION.get(countries[0], "EU")

        sup_tiers = self._pricing[
            (self._pricing["supplier_id"] == sup_id) &
            (self._pricing["category_l1"] == cat1) &
            (self._pricing["category_l2"] == cat2) &
            (self._pricing["region"]      == region)
        ].sort_values("min_quantity")

        if sup_tiers.empty:
            return levers

        # Current tier
        current_rows = sup_tiers[
            (sup_tiers["min_quantity"] <= qty) & (sup_tiers["max_quantity"] >= qty)
        ]
        if current_rows.empty:
            return levers

        current_unit  = float(current_rows.iloc[0]["unit_price"])
        current_max   = float(current_rows.iloc[0]["max_quantity"])
        price_ccy     = str(current_rows.iloc[0]["currency"])

        # Is there a cheaper next tier?
        next_tiers = sup_tiers[sup_tiers["min_quantity"] > current_max]
        if next_tiers.empty:
            return levers

        next_tier     = next_tiers.iloc[0]
        next_unit     = float(next_tier["unit_price"])
        next_min_qty  = float(next_tier["min_quantity"])

        if next_unit >= current_unit:
            return levers   # next tier not cheaper

        units_to_add  = next_min_qty - qty
        if units_to_add > qty * 1.0:  # 100% for demo
            return levers   # adding > 20% is not practical

        # Economics: new total cost vs old total cost
        new_total_eur = _to_eur(next_unit, price_ccy) * next_min_qty
        old_total_eur = _to_eur(current_unit, price_ccy) * qty
        saving_eur    = old_total_eur - new_total_eur
        saving_local  = _from_eur(saving_eur, currency)
        saving_pct    = (saving_local / contract * 100) if contract > 0 else 0

        if saving_eur < 50: # 50 for demo
            return levers

        levers.append(NegotiationLever(
            type="quantity_increase",
            description=(
                f"Increasing the order by {units_to_add:.0f} units "
                f"(from {qty:.0f} to {next_min_qty:.0f}) unlocks the next "
                f"pricing tier with {top['supplier_name']} at a lower unit price, "
                f"saving {saving_local:,.0f} {currency} ({saving_pct:.1f}%) "
                f"even accounting for the extra units."
            ),
            parameter_change={"quantity": next_min_qty},
            saving_amount=round(saving_local, 2),
            saving_pct=round(saving_pct, 2),
            new_supplier=None,
            original_supplier=top.get("supplier_name"),
            confidence="HIGH",
            detail=(
                f"Current tier unit price: {current_unit} {price_ccy} × {qty:.0f} units. "
                f"Next tier unit price: {next_unit} {price_ccy} × {next_min_qty:.0f} units. "
                f"Extra units needed: {units_to_add:.0f}."
            ),
        ))
        return levers

    # ─────────────────────────────────────────────────────────────────────────
    # LEVER 5: ESG waiver
    # ─────────────────────────────────────────────────────────────────────────

    def _lever_esg_waiver(
        self,
        request: dict,
        engine_output: dict,
        top: dict,
        currency: str,
        contract: float,
    ) -> list[NegotiationLever]:
        """
        If esg_requirement=True and there are excluded suppliers that would
        otherwise qualify, show what waiving it unlocks.
        """
        levers = []
        if not request.get("esg_requirement"):
            return levers

        # Count how many suppliers were excluded due to ESG in the audit trail
        excluded = engine_output.get("audit_trail", {}).get(
            "suppliers_excluded_esg", []
        )
        shortlist = engine_output.get("supplier_shortlist", [])
        n_excluded = len(excluded)

        if n_excluded == 0:
            # Still useful: compare to lowest ESG supplier in shortlist
            low_esg = min(shortlist, key=lambda s: float(s.get("esg_score", 100)),
                          default=None)
            if not low_esg or float(low_esg.get("esg_score", 100)) >= 60:
                return levers

        levers.append(NegotiationLever(
            type="esg_waiver",
            description=(
                f"The ESG requirement is currently set. "
                + (f"Waiving it would add {n_excluded} excluded supplier(s) "
                   f"to the shortlist, potentially improving competition and pricing."
                   if n_excluded > 0
                   else "Relaxing the ESG threshold below the current 60-point floor "
                        "would expand the eligible supplier pool.")
            ),
            parameter_change={"esg_requirement": False},
            saving_amount=0.0,
            saving_pct=0.0,
            new_supplier=excluded[0] if excluded else None,
            original_supplier=top.get("supplier_name"),
            confidence="LOW",
            detail=(
                "ESG waivers require Head of Category approval per category rules. "
                "Potential saving depends on excluded supplier pricing — "
                "re-run the pipeline with esg_requirement=False to quantify."
            ),
        ))
        return levers

    # ─────────────────────────────────────────────────────────────────────────
    # LEVER 6: Country split delivery
    # ─────────────────────────────────────────────────────────────────────────

    def _lever_country_split(
        self,
        request: dict,
        engine_output: dict,
        top: dict,
        currency: str,
        contract: float,
    ) -> list[NegotiationLever]:
        """
        If a runner-up was excluded because it doesn't cover ALL delivery
        countries, suggest splitting the order: runner-up covers the countries
        it can, top supplier covers the rest.
        """
        levers    = []
        countries = request.get("delivery_countries") or []
        if len(countries) <= 1:
            return levers   # single country — split doesn't apply

        excluded  = engine_output.get("audit_trail", {}).get(
            "suppliers_excluded_geography", []
        )
        if not excluded:
            return levers

        for exc in excluded[:2]:   # max 2 suggestions
            exc_name     = exc.get("supplier_name", "?")
            exc_covers   = exc.get("covers_countries", [])
            uncovered    = [c for c in countries if c not in exc_covers]

            if not exc_covers or len(exc_covers) == len(countries):
                continue

            levers.append(NegotiationLever(
                type="country_split",
                description=(
                    f"{exc_name} covers {exc_covers} but not {uncovered}. "
                    f"Splitting the delivery: {exc_name} for {exc_covers} "
                    f"and {top['supplier_name']} for {uncovered} "
                    f"may reduce total cost. Requires dual-PO management."
                ),
                parameter_change={
                    "split_delivery": {
                        "supplier_a": exc_name,
                        "countries_a": exc_covers,
                        "supplier_b": top.get("supplier_name"),
                        "countries_b": uncovered,
                    }
                },
                saving_amount=0.0,
                saving_pct=0.0,
                new_supplier=exc_name,
                original_supplier=top.get("supplier_name"),
                confidence="LOW",
                detail=(
                    "Saving depends on pricing delta between suppliers per country. "
                    "Re-run the pipeline per country to quantify. "
                    "Note: dual-PO splits may require additional approval per policy."
                ),
            ))

        return levers

    # ─────────────────────────────────────────────────────────────────────────

    def _load_pricing(self) -> pd.DataFrame:
        for p in [
            self.data_dir / "merged_v2.csv",
            self.data_dir / "../data/merged_v2.csv",
            self.data_dir / "pricing.csv",
            self.data_dir / "../data/pricing.csv",
        ]:
            if p.exists():
                try:
                    return pd.read_csv(p)
                except Exception:
                    pass
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE INTEGRATION  — 2 lines in pipeline.py
# ══════════════════════════════════════════════════════════════════════════════

def attach_negotiation_levers(
    engine_output: dict,
    request: dict,
    data_dir: str | Path = "data",
) -> dict:
    """
    Convenience one-liner for pipeline.py:

        from optimization_engine import attach_negotiation_levers
        final_output = attach_negotiation_levers(final_output, working_request)
    """
    advisor = NegotiationAdvisor(data_dir=data_dir)
    levers  = advisor.advise(engine_output, request)
    engine_output["negotiation_levers"] = [asdict(l) for l in levers]
    return engine_output


def attach_bundle_opportunities(
    engine_output: dict,
    all_requests: list[dict],
    awarded_ids: set[str],
    data_dir: str | Path = "data",
) -> dict:
    """
    Attach relevant bundle opportunities to a single request's output.
    Filters to bundles that include this request's ID.

        from optimization_engine import attach_bundle_opportunities
        final_output = attach_bundle_opportunities(
            final_output, all_requests, awarded_ids
        )
    """
    req_id = engine_output.get("request_id", "")
    agg    = DemandAggregator(data_dir=data_dir)
    all_bundles = agg.find_opportunities(all_requests, awarded_ids)
    relevant    = [
        asdict(b) for b in all_bundles
        if req_id in b.request_ids
    ]
    engine_output["bundle_opportunities"] = relevant
    return engine_output


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    from pathlib import Path

    base = Path(__file__).parent
    data_dir = base / "data"

    # ── Demo: Demand Aggregation ─────────────────────────────────────────────
    req_path = data_dir / "requests.json"
    awd_path = data_dir / "historical_awards.csv"

    if req_path.exists():
        requests = json.loads(req_path.read_text())
        awarded_ids: set[str] = set()
        if awd_path.exists():
            awd = pd.read_csv(awd_path)
            awarded_ids = set(awd["request_id"].dropna().astype(str))

        print("[DemandAggregator] Scanning all requests for bundle opportunities...")
        agg     = DemandAggregator(data_dir=data_dir)
        bundles = agg.find_opportunities(requests, awarded_ids)
        print(agg.summary_report(bundles))

        # Save for pipeline consumption
        out = base / "bundle_opportunities.json"
        out.write_text(json.dumps([asdict(b) for b in bundles], indent=2))
        print(f"Saved → {out}")
    else:
        print("[DemandAggregator] requests.json not found — skipping demo.")

    # ── Demo: Negotiation Advisor ────────────────────────────────────────────
    output_path = base / "output_final.json"
    if output_path.exists():
        outputs = json.loads(output_path.read_text())
        sample_output  = outputs[0] if isinstance(outputs, list) else outputs

        # Reconstruct the original request from the output
        sample_request = sample_output.get("request", sample_output)

        advisor = NegotiationAdvisor(data_dir=data_dir)
        levers  = advisor.advise(sample_output, sample_request)

        print("\n[NegotiationAdvisor] Levers for",
              sample_request.get("request_id", "?"))
        print("=" * 72)
        for i, l in enumerate(levers, 1):
            print(f"\n[{i}] {l.type.upper()} — {l.confidence} confidence")
            print(f"    {l.description}")
            if l.saving_amount != 0:
                sign = "+" if l.saving_amount > 0 else ""
                print(f"    Impact: {sign}{l.saving_amount:,.0f}"
                      f"  ({sign}{l.saving_pct:.1f}%)")
            print(f"    Change: {json.dumps(l.parameter_change)}")
        print("=" * 72)
    else:
        print("[NegotiationAdvisor] output_final.json not found — skipping demo.")
