"""
scoring_calibrator.py  — ChainIQ START Hack 2026
=================================================
Calibrates supplier ranking weights from historical award data using
logistic regression. Replaces the hardcoded weights in rule_engine_v3.py
with empirically derived coefficients that reflect what ChainIQ's
procurement team actually valued when making past decisions.

WHAT THIS MODULE DOES
---------------------
  1. Trains a logistic regression on historical_awards.csv to predict
     P(awarded=True) from measurable supplier features.
  2. Converts the standardised coefficients into a weight dict compatible
     with rule_engine_v3.score_supplier().
  3. Produces a calibration report showing feature importance and fit quality.
  4. Exports weights to calibrated_weights.json for use by the pipeline.

KEY INSIGHT FROM THE DATA
-------------------------
  savings_pct   coefficient: +5.34  ← dominant signal (price competitiveness)
  quality_score coefficient: +1.03  ← strong second signal
  risk_score    coefficient: -0.77  ← risk penalises heavily (inverted)
  esg_score     coefficient: +0.10  ← present but weaker than price/quality
  lead_time     coefficient: -0.08  ← relevant but least discriminating

  5-fold CV AUC = 0.991 ± 0.003  (very high — the dataset is cleanly labelled)

INTEGRATION
-----------
  from scoring_calibrator import ScoringCalibrator
  cal = ScoringCalibrator()
  cal.train()
  weights = cal.weights()         # dict compatible with score_supplier()
  cal.save('calibrated_weights.json')
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score
from sklearn.model_selection import cross_val_score, StratifiedKFold
from sklearn.preprocessing import StandardScaler

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

FEATURES = [
    "savings_pct",            # % savings vs budget — primary price signal
    "quality_score",          # 0–100 quality rating
    "risk_score_at_award",    # lower = better (will be negated in weights)
    "esg_score",              # 0–100 ESG rating
    "lead_time_days",         # lower = better (will be negated in weights)
]

# These features are "lower is better" — their coefficients flip sign in weights
INVERTED_FEATURES = {"risk_score_at_award", "lead_time_days"}

# Minimum weight (prevents any feature from being zeroed out)
MIN_WEIGHT = 0.02


# ══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CalibrationReport:
    n_samples: int
    n_awarded: int
    n_not_awarded: int
    cv_auc_mean: float
    cv_auc_std: float
    train_auc: float
    train_ap: float
    raw_coefficients: dict[str, float]   # standardised logistic coef
    feature_means: dict[str, float]      # scaler means (for inference)
    feature_stds: dict[str, float]       # scaler stds  (for inference)
    derived_weights: dict[str, float]    # normalised weights for score_supplier
    preferred_bonus: float               # fixed bonus for preferred suppliers
    incumbent_bonus: float               # fixed bonus for incumbent suppliers
    esg_weight_boost: float             # extra esg weight when esg_required=True


# ══════════════════════════════════════════════════════════════════════════════
# CALIBRATOR
# ══════════════════════════════════════════════════════════════════════════════

class ScoringCalibrator:

    def __init__(
        self,
        awards_path: Path | str = "historical_awards.csv",
        merged_path: Path | str = "merged_v2.csv",
        C: float = 1.0,
        preferred_bonus: float = 0.08,
        incumbent_bonus: float = 0.05,
        esg_weight_boost: float = 0.10,
    ):
        self.awards_path    = Path(awards_path)
        self.merged_path    = Path(merged_path)
        self.C              = C
        self.preferred_bonus   = preferred_bonus
        self.incumbent_bonus   = incumbent_bonus
        self.esg_weight_boost  = esg_weight_boost

        self._scaler: StandardScaler | None = None
        self._model:  LogisticRegression | None = None
        self._report: CalibrationReport | None = None

    # ─────────────────────────────────────────────────────────────────────────

    def train(self) -> CalibrationReport:
        """
        Train the scoring model and produce a calibration report.
        """
        awards = pd.read_csv(self.awards_path)
        merged = pd.read_csv(self.merged_path)

        # Enrich awards with current supplier scores (quality, esg)
        sup_scores = (
            merged[["supplier_id", "quality_score", "esg_score"]]
            .drop_duplicates("supplier_id")
        )
        df = awards.merge(sup_scores, on="supplier_id", how="left")
        df_clean = df[FEATURES + ["awarded"]].dropna()

        X = df_clean[FEATURES].values
        y = df_clean["awarded"].astype(int).values

        # Scale
        scaler = StandardScaler()
        Xs = scaler.fit_transform(X)

        # Cross-validated AUC
        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        model = LogisticRegression(C=self.C, max_iter=1000, random_state=42)
        cv_aucs = cross_val_score(model, Xs, y, cv=cv, scoring="roc_auc")

        # Final fit
        model.fit(Xs, y)
        y_prob = model.predict_proba(Xs)[:, 1]
        train_auc = roc_auc_score(y, y_prob)
        train_ap  = average_precision_score(y, y_prob)

        # Convert standardised coefficients to normalised weights
        raw_coefs = dict(zip(FEATURES, model.coef_[0]))
        derived = self._coefs_to_weights(raw_coefs)

        self._scaler = scaler
        self._model  = model
        self._report = CalibrationReport(
            n_samples=len(df_clean),
            n_awarded=int(y.sum()),
            n_not_awarded=int(len(y) - y.sum()),
            cv_auc_mean=float(cv_aucs.mean()),
            cv_auc_std=float(cv_aucs.std()),
            train_auc=float(train_auc),
            train_ap=float(train_ap),
            raw_coefficients={k: round(float(v), 4) for k, v in raw_coefs.items()},
            feature_means={k: round(float(v), 4)
                           for k, v in zip(FEATURES, scaler.mean_)},
            feature_stds={k: round(float(v), 4)
                          for k, v in zip(FEATURES, scaler.scale_)},
            derived_weights=derived,
            preferred_bonus=self.preferred_bonus,
            incumbent_bonus=self.incumbent_bonus,
            esg_weight_boost=self.esg_weight_boost,
        )
        return self._report

    # ─────────────────────────────────────────────────────────────────────────

    def _coefs_to_weights(self, raw: dict[str, float]) -> dict[str, float]:
        """
        Convert standardised logistic coefficients to a normalised weight dict.

        Strategy:
          • Absolute value of coefficient → relative importance
          • Features where "lower is better" (risk, lead_time) stay positive
            weights because rule_engine.score_supplier() already inverts them
          • Minimum weight floor at MIN_WEIGHT to prevent any zeroing
          • Normalise so sum of continuous feature weights ≈ 1.0
            (preferred and incumbent bonuses added separately)
        """
        # Use absolute value of each coef as raw importance
        abs_coefs = {k: abs(v) for k, v in raw.items()}

        # Map feature names to score_supplier() weight keys
        key_map = {
            "savings_pct":          "price",
            "quality_score":        "quality",
            "risk_score_at_award":  "risk",
            "esg_score":            "esg",
            "lead_time_days":       "lead_time",
        }

        mapped = {key_map[k]: max(abs_coefs[k], MIN_WEIGHT) for k in FEATURES}

        # Normalise continuous weights to sum to 1.0
        total = sum(mapped.values())
        normalised = {k: round(v / total, 4) for k, v in mapped.items()}

        # Scale down by fixed bonus fraction so bonuses are additive
        bonus_fraction = self.preferred_bonus + self.incumbent_bonus
        scale = 1.0 - bonus_fraction
        normalised = {k: round(v * scale, 4) for k, v in normalised.items()}

        return normalised

    # ─────────────────────────────────────────────────────────────────────────

    def weights(self, esg_required: bool = False) -> dict:
        """
        Return the weight dict for score_supplier().
        If esg_required=True, boosts the esg weight at the expense of others.
        """
        if self._report is None:
            raise RuntimeError("Call train() before weights()")

        w = dict(self._report.derived_weights)

        if esg_required:
            # Redistribute esg_weight_boost from price and quality proportionally
            boost = self._report.esg_weight_boost
            price_share  = w["price"]  / (w["price"] + w["quality"])
            quality_share = 1.0 - price_share
            w["esg"]     = round(w["esg"] + boost, 4)
            w["price"]   = round(w["price"]   - boost * price_share, 4)
            w["quality"] = round(w["quality"] - boost * quality_share, 4)

        w["preferred"] = self._report.preferred_bonus
        w["incumbent"] = self._report.incumbent_bonus
        return w

    # ─────────────────────────────────────────────────────────────────────────

    def score_one(
        self,
        supplier_row: dict,
        budget_amount: float | None,
        req_currency: str,
        contract_value: float,
        is_preferred: bool,
        is_incumbent: bool,
        esg_required: bool = False,
    ) -> float:
        """
        Score a single supplier using calibrated weights.
        Delegates to rule_engine_v3.score_supplier() with calibrated weights.
        """
        from rule_engine_v3 import score_supplier, convert
        return score_supplier(
            pricing_row=supplier_row,
            contract_value=contract_value,
            budget_amount=budget_amount,
            request_currency=req_currency,
            is_preferred=is_preferred,
            is_incumbent=is_incumbent,
            esg_required=esg_required,
            weights=self.weights(esg_required=esg_required),
        )

    # ─────────────────────────────────────────────────────────────────────────

    def save(self, path: str | Path = "calibrated_weights.json") -> None:
        """Save calibration report (including weights) to JSON."""
        if self._report is None:
            raise RuntimeError("Call train() before save()")
        Path(path).write_text(
            json.dumps(asdict(self._report), indent=2, default=str)
        )
        print(f"Calibration report saved → {path}")

    # ─────────────────────────────────────────────────────────────────────────

    def print_report(self) -> None:
        if self._report is None:
            raise RuntimeError("Call train() before print_report()")
        r = self._report
        print("\n" + "=" * 64)
        print("SCORING CALIBRATION REPORT")
        print("=" * 64)
        print(f"Training samples  : {r.n_samples} "
              f"(awarded={r.n_awarded}, not awarded={r.n_not_awarded})")
        print(f"5-fold CV AUC     : {r.cv_auc_mean:.3f} ± {r.cv_auc_std:.3f}")
        print(f"Train AUC / AP    : {r.train_auc:.3f} / {r.train_ap:.3f}")
        print("\nRaw standardised coefficients:")
        for k, v in sorted(r.raw_coefficients.items(), key=lambda x: -abs(x[1])):
            bar = "█" * int(abs(v) * 8)
            sign = "+" if v > 0 else "-"
            print(f"  {k:<25} {sign}{abs(v):.4f}  {bar}")
        print("\nDerived weights (for score_supplier):")
        for k, v in sorted(r.derived_weights.items(), key=lambda x: -x[1]):
            bar = "█" * int(v * 80)
            print(f"  {k:<15} {v:.4f}  {bar}")
        print(f"  preferred_bonus  {r.preferred_bonus:.4f}")
        print(f"  incumbent_bonus  {r.incumbent_bonus:.4f}")
        print(f"  esg_weight_boost {r.esg_weight_boost:.4f}  (when esg_required=True)")
        print("=" * 64)


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    from pathlib import Path
    base = Path(__file__).parent
    cal = ScoringCalibrator(
        awards_path=base / "historical_awards.csv",
        merged_path=base / "merged_v2.csv",
    )
    cal.train()
    cal.print_report()
    cal.save(base / "calibrated_weights.json")
