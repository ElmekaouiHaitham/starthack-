"""
pipeline.py  — ChainIQ START Hack 2026
=======================================
Main orchestrator. Wires the four layers into a single clean interface.

ARCHITECTURE
------------

    ┌─────────────────────────────────────────────────────┐
    │  1. NLPExtractor          (nlp_extractor.py)        │
    │     • Language detection + translation              │
    │     • Quantity / budget extraction from text        │
    │     • Policy refusal detection                      │
    │     • Contradiction detection (deterministic)       │
    └───────────────────┬─────────────────────────────────┘
                        │  enriched request dict
    ┌───────────────────▼─────────────────────────────────┐
    │  2. ProcurementRuleEngine (rule_engine_v3.py)       │
    │     • Supplier eligibility + restriction checks     │
    │     • Pricing tier selection + MOQ validation       │
    │     • Approval threshold + escalation routing       │
    │     • Multi-criteria ranking                        │
    └───────────────────┬─────────────────────────────────┘
                        │  structured engine output
    ┌───────────────────▼─────────────────────────────────┐
    │  3. ScoringCalibrator     (scoring_calibrator.py)   │
    │     • Logistic regression weights from historical   │
    │       awards (CV AUC 0.991)                        │
    │     • Re-scores shortlist with calibrated weights   │
    └───────────────────┬─────────────────────────────────┘
                        │  re-ranked output
    ┌───────────────────▼─────────────────────────────────┐
    │  4. RationaleGenerator    (rationale_generator.py)  │
    │     • Adds per-supplier recommendation_notes        │
    │     • Writes recommendation.reason paragraph        │
    │     • Uses few-shot examples from historical awards │
    └───────────────────┬─────────────────────────────────┘
                        │  final audit-ready output JSON
                        ▼

USAGE
-----

  # Single request (dict)
  from pipeline import Pipeline
  pipe = Pipeline()
  result = pipe.run(request_dict)

  # Full batch
  results = pipe.run_batch(requests_list, output_path="output_final.json")

  # CLI
  python3 pipeline.py                     # process all 304 requests
  python3 pipeline.py --n 10             # first 10 only
  python3 pipeline.py --id REQ-000004    # single request by ID
  python3 pipeline.py --no-nlp           # skip NLP layer (offline mode)
  python3 pipeline.py --no-rationale     # skip rationale layer (faster)

LAYERS CAN BE DISABLED
-----------------------
  NLP and rationale layers require ANTHROPIC_API_KEY.
  If disabled, the pipeline falls back to structured-field-only processing
  and template rationale — still fully functional, just less rich.

CACHING
-------
  NLP results      → nlp_cache.json
  Rationale text   → rationale_cache.json
  Calibration      → calibrated_weights.json
  Delete any cache file to force re-run for that layer.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# ══════════════════════════════════════════════════════════════════════════════
# IMPORTS
# ══════════════════════════════════════════════════════════════════════════════

from rule_engine_v3 import ProcurementRuleEngine
from scoring_calibrator import ScoringCalibrator
from nlp_extractor import NLPExtractor, apply_nlp_to_rule_engine_input
from rationale_generator import RationaleGenerator, _template_fallback, _merge_rationale
from optimization_engine import NegotiationAdvisor, DemandAggregator
from historical_analytics import HistoricalAnalytics
from dataclasses import asdict

DATA_DIR = Path(__file__).parent


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

class Pipeline:
    """
    Full procurement agent pipeline.

    Parameters
    ----------
    data_dir        : directory containing all data files
    enable_nlp      : whether to call the NLP extraction layer (requires API key)
    enable_rationale: whether to call the rationale generation layer (requires API key)
    force_refresh   : ignore all caches and re-run everything
    """

    def __init__(
        self,
        data_dir: Path = DATA_DIR,
        enable_nlp: bool = True,
        enable_rationale: bool = True,
        enable_optimization: bool = True,
        enable_bundling: bool = True,
        force_refresh: bool = False,
    ):
        self.data_dir         = data_dir
        self.enable_nlp       = enable_nlp
        self.enable_rationale = enable_rationale
        self.enable_optimization = enable_optimization
        self.enable_bundling  = enable_bundling
        self.force_refresh    = force_refresh

        # Always-on: rule engine + calibrator
        print("Loading rule engine…")
        self.engine = ProcurementRuleEngine(data_dir=data_dir)

        print("Training scoring calibrator…")
        self.calibrator = ScoringCalibrator(
            awards_path=data_dir / "../data/historical_awards.csv",
            merged_path=data_dir / "../data/merged_v2.csv",
        )
        self.calibrator.train()
        print(f"  Calibrated CV-AUC: {self.calibrator._report.cv_auc_mean:.3f}")

        # Optional layers
        self.nlp_extractor: NLPExtractor | None = None
        if enable_nlp:
            try:
                print("Initialising NLP extractor…")
                self.nlp_extractor = NLPExtractor(
                    cache_path=data_dir / "../data/nlp_cache.json",
                )
            except EnvironmentError as e:
                print(f"  WARNING: NLP layer disabled — {e}")
                self.enable_nlp = False

        self.rationale_gen: RationaleGenerator | None = None
        if enable_rationale:
            try:
                print("Initialising rationale generator…")
                self.rationale_gen = RationaleGenerator(
                    awards_path=data_dir / "../data/historical_awards.csv",
                    cache_path=data_dir / "../data/rationale_cache.json",
                )
            except EnvironmentError as e:
                print(f"  WARNING: Rationale layer disabled — {e}")
                self.enable_rationale = False

        self.advisor: NegotiationAdvisor | None = None
        if self.enable_optimization:
            print("Initialising Negotiation Advisor…")
            self.advisor = NegotiationAdvisor(data_dir=data_dir)

        self.aggregator: DemandAggregator | None = None
        if self.enable_bundling:
            print("Initialising Demand Aggregator…")
            self.aggregator = DemandAggregator(data_dir=data_dir)

        print("Initialising Historical Analytics…")
        self.analytics = HistoricalAnalytics(data_dir=data_dir / "../data")

        print("Pipeline ready.\n")

    # ─────────────────────────────────────────────────────────────────────────
    # SINGLE REQUEST
    # ─────────────────────────────────────────────────────────────────────────

    def run(self, request: dict) -> dict:
        """
        Process one request through all four layers.
        Returns the final audit-ready output dict.
        """
        req_id = request.get("request_id", "unknown")

        # ── Layer 1: NLP extraction ──────────────────────────────────────────
        if self.enable_nlp and self.nlp_extractor:
            try:
                enriched = self.nlp_extractor.enrich(
                    request, force_refresh=self.force_refresh
                )
                working_request = apply_nlp_to_rule_engine_input(enriched)
            except Exception as e:
                print(f"    NLP failed for {req_id}: {e} — using raw fields")
                working_request = request
        else:
            working_request = request

        # ── Layer 2: Rule engine ─────────────────────────────────────────────
        engine_output = self.engine.process(working_request)

        # ── Layer 3: Re-score with calibrated weights ────────────────────────
        engine_output = self._apply_calibrated_scores(engine_output, working_request)

        # ── Layer 3b: Historical analytics insights ──────────────────────────
        engine_output = self.analytics.attach(engine_output, working_request)

        # ── Layer 4: Rationale generation ────────────────────────────────────
        if self.enable_rationale and self.rationale_gen:
            try:
                final_output = self.rationale_gen.add_rationale(
                    engine_output, force_refresh=self.force_refresh
                )
            except Exception as e:
                print(f"    Rationale failed for {req_id}: {e} — using template")
                rationale = _template_fallback(engine_output, str(e))
                final_output = _merge_rationale(engine_output, rationale)
        else:
            rationale = _template_fallback(engine_output, "rationale layer disabled")
            final_output = _merge_rationale(engine_output, rationale)

        # Add pipeline metadata
        final_output["_pipeline"] = {
            "nlp_enabled":       self.enable_nlp,
            "rationale_enabled": self.enable_rationale,
            "optimization_enabled": self.enable_optimization,
            "bundling_enabled":  self.enable_bundling,
            "calibration_auc":   round(self.calibrator._report.cv_auc_mean, 3),
            "pipeline_version":  "v1.0",
        }

        # ── Layer 5: Negotiation Advisor ──────────────────────────────────────
        run_opt = request.get("_enable_optimization", self.enable_optimization)
        if run_opt and self.advisor:
            levers = self.advisor.advise(final_output, request)
            final_output["negotiation_levers"] = [asdict(l) for l in levers]

        return final_output

    # ─────────────────────────────────────────────────────────────────────────
    # SINGLE REQUEST STREAMING
    # ─────────────────────────────────────────────────────────────────────────

    def run_stream(self, request: dict):
        """
        Process request and yield thinking steps followed by final result.
        """
        req_id = request.get("request_id", "unknown")
        
        yield {"type": "step", "title": "Request Received", "description": f"Looking up details for your request {req_id}"}
        time.sleep(0.5)

        # ── Layer 1: NLP extraction ──────────────────────────────────────────
        yield {"type": "step", "title": "Reading the Request", "description": "I'm reading your request and figuring out exactly what you need"}
        if self.enable_nlp and self.nlp_extractor:
            try:
                enriched = self.nlp_extractor.enrich(
                    request, force_refresh=self.force_refresh
                )
                working_request = apply_nlp_to_rule_engine_input(enriched)
                yield {"type": "step", "title": "Understanding Complete", "description": "I have successfully pulled out all the required details from your request"}
            except Exception as e:
                print(f"    NLP failed for {req_id}: {e} — using raw fields")
                working_request = request
                yield {"type": "step", "title": "Reading Failed", "description": f"I had a little trouble understanding the text: {e}. I'll just use the form fields provided"}
        else:
            working_request = request
            yield {"type": "step", "title": "Reading Skipped", "description": "I'll skip reading the text since that's turned off right now"}

        # ── Layer 2: Rule engine ─────────────────────────────────────────────
        yield {"type": "step", "title": "Checking Policies", "description": "Looking at company rules to see which suppliers we can use and what approvals are needed"}
        engine_output = self.engine.process(working_request)
        yield {"type": "step", "title": "Policy Check Complete", "description": f"I found {len(engine_output.get('supplier_shortlist', []))} suppliers that match the rules"}
        time.sleep(0.5)

        # ── Layer 3: Re-score with calibrated weights ────────────────────────
        yield {"type": "step", "title": "Finding Best Options", "description": "Comparing the available suppliers to figure out the best match for this request"}
        engine_output = self._apply_calibrated_scores(engine_output, working_request)
        yield {"type": "step", "title": "Ranking Complete", "description": "I've ranked the best suppliers for you"}
        time.sleep(0.5)

        # ── Layer 3b: Historical analytics insights ──────────────────────────
        yield {"type": "step", "title": "Checking Escalation Feasibility", "description": "Comparing escalation cycle history with your required delivery date to see if the normal process is fast enough"}
        engine_output = self.analytics.attach(engine_output, working_request)

        # ── Layer 4: Rationale generation ────────────────────────────────────
        yield {"type": "step", "title": "Writing Recommendation", "description": "Putting together a clear explanation of my final decision for your review"}
        if self.enable_rationale and self.rationale_gen:
            try:
                final_output = self.rationale_gen.add_rationale(
                    engine_output, force_refresh=self.force_refresh
                )
                yield {"type": "step", "title": "Recommendation Complete", "description": "I have finished writing the final recommendation"}
            except Exception as e:
                print(f"    Rationale failed for {req_id}: {e} — using template")
                rationale = _template_fallback(engine_output, str(e))
                final_output = _merge_rationale(engine_output, rationale)
                yield {"type": "step", "title": "Recommendation Fallback", "description": "I've used a standard template for the recommendation due to a small error"}
        else:
            rationale = _template_fallback(engine_output, "rationale layer disabled")
            final_output = _merge_rationale(engine_output, rationale)
            yield {"type": "step", "title": "Recommendation Skipped", "description": "Skipping the custom written recommendation and using a standard template instead"}

        # Add pipeline metadata
        final_output["_pipeline"] = {
            "nlp_enabled":       self.enable_nlp,
            "rationale_enabled": self.enable_rationale,
            "optimization_enabled": self.enable_optimization,
            "bundling_enabled":  self.enable_bundling,
            "calibration_auc":   round(self.calibrator._report.cv_auc_mean, 3),
            "pipeline_version":  "v1.0",
        }

        run_opt = request.get("_enable_optimization", self.enable_optimization)
        if run_opt and self.advisor:
            yield {"type": "step", "title": "Optimizing Strategy", "description": "Looking for negotiation levers to improve the contract value"}
            levers = self.advisor.advise(final_output, request)
            final_output["negotiation_levers"] = [asdict(l) for l in levers]
            if levers:
                yield {"type": "step", "title": "Optimization Complete", "description": f"Found {len(levers)} potential negotiation levers"}

        # Store input for batch-level bundling if enabled
        run_bundle = request.get("_enable_bundling", self.enable_bundling)
        if run_bundle:
            self._last_request_for_bundling = request

        yield {"type": "result", "data": final_output}

    # ─────────────────────────────────────────────────────────────────────────
    # CALIBRATED RESCORING
    # ─────────────────────────────────────────────────────────────────────────

    def _apply_calibrated_scores(self, engine_output: dict, request: dict) -> dict:
        """
        Replace the rule engine's hardcoded-weight scores with calibrated scores,
        then re-sort the shortlist.

        The calibrator was trained on (savings_pct, quality, risk, esg, lead_time).
        We compute savings_pct at scoring time from budget vs. total price.
        """
        import json as _json
        out = _json.loads(_json.dumps(engine_output))   # deep copy

        budget      = request.get("budget_amount")
        req_ccy     = request.get("currency", "EUR")
        esg_req     = request.get("esg_requirement", False)
        incumbent   = request.get("incumbent_supplier")
        weights     = self.calibrator.weights(esg_required=bool(esg_req))

        shortlist = out.get("supplier_shortlist", [])
        for s in shortlist:
            # Compute savings_pct: (budget - total_in_req_ccy) / budget
            total_req_ccy = s.get("total_price_in_req_currency", 0)
            savings_pct = 0.0
            if budget and budget > 0:
                savings_pct = max(0.0, (budget - total_req_ccy) / budget * 100)

            # Build a synthetic pricing_row compatible with score_supplier()
            pricing_row = {
                "quality_score":          s.get("quality_score", 50),
                "risk_score":             s.get("risk_score", 50),
                "esg_score":              s.get("esg_score", 50),
                "currency":               s.get("pricing_currency", req_ccy),
            }

            # Calibrated score
            raw_score = (
                weights.get("price",  0) * min(1.0, savings_pct / 10)   # normalise savings_pct
                + weights.get("quality",  0) * pricing_row["quality_score"] / 100
                + weights.get("risk",     0) * (1 - pricing_row["risk_score"] / 100)
                + weights.get("esg",      0) * pricing_row["esg_score"] / 100
                + weights.get("lead_time",0) * _lead_time_score(s.get("lead_time_days", 30))
                + weights.get("preferred",0) * float(bool(s.get("preferred")))
                + weights.get("incumbent",0) * float(bool(
                    incumbent and incumbent == s.get("supplier_name")
                ))
            )
            s["score"]          = round(raw_score, 4)
            s["score_weights"]  = {k: round(v, 4) for k, v in weights.items()}
            s["savings_pct_vs_budget"] = round(savings_pct, 2)

        # Re-sort by calibrated score
        shortlist.sort(key=lambda x: x["score"], reverse=True)
        for i, s in enumerate(shortlist):
            s["rank"] = i + 1

        out["supplier_shortlist"] = shortlist
        out["audit_trail"]["scoring_weights_used"] = weights
        return out

    # ─────────────────────────────────────────────────────────────────────────
    # BATCH
    # ─────────────────────────────────────────────────────────────────────────

    def run_batch(
        self,
        requests: list[dict],
        output_path: str | Path | None = None,
        verbose: bool = True,
    ) -> list[dict]:
        """
        Process all requests. Saves to output_path if specified.
        Returns list of final output dicts.
        """
        if verbose:
            print(f"Processing {len(requests)} requests…\n")

        results = []
        errors  = []
        t0 = time.time()
        bundle_opps = []

        for i, req in enumerate(requests):
            req_id = req.get("request_id", f"idx_{i}")
            try:
                result = self.run(req)
                results.append(result)
                if verbose:
                    status = result["recommendation"]["status"]
                    n_esc  = len(result.get("escalations", []))
                    n_sup  = len(result.get("supplier_shortlist", []))
                    print(f"  [{i+1:3d}/{len(requests)}] {req_id} "
                          f"status={status} "
                          f"suppliers={n_sup} escalations={n_esc}")
            except Exception as e:
                errors.append({"request_id": req_id, "error": str(e)})
                if verbose:
                    print(f"  [{i+1:3d}/{len(requests)}] {req_id} ERROR: {e}")

        elapsed = time.time() - t0
        if verbose:
            print(f"\nCompleted in {elapsed:.1f}s "
                  f"({len(results)} ok, {len(errors)} errors)")

        if output_path:
            Path(output_path).write_text(
                json.dumps(results, indent=2, default=str)
            )
            if verbose:
                print(f"Saved → {output_path}")

        # ── Cross-Batch Demand Aggregation ──────────────────────────────────
        # Check if any request requested bundling OR if pipeline default is true
        any_bundling_requested = any(r.get("_enable_bundling", self.enable_bundling) for r in requests)
        
        if any_bundling_requested and self.aggregator:
            if verbose:
                print("\nRunning Demand Aggregation across batch…")
            opps = self.aggregator.find_opportunities(requests)
            bundle_opps = [asdict(o) for o in opps]
            if verbose:
                print(self.aggregator.summary_report(opps))

            # Since the API primarily returns per-request outputs, and bundle_opps is a cross-request aggregate,
            # we attach the bundle_opps to all request outputs in the batch so the frontend receives them.
            if bundle_opps:
                for r in results:
                    r["bundle_opportunities"] = bundle_opps

        if verbose:
            self._print_summary(results)

        return results

    # ─────────────────────────────────────────────────────────────────────────
    # SUMMARY REPORT
    # ─────────────────────────────────────────────────────────────────────────

    def _print_summary(self, results: list[dict]) -> None:
        from collections import Counter
        statuses = Counter(r["recommendation"]["status"] for r in results)
        rules    = Counter(
            e["rule"]
            for r in results
            for e in r.get("escalations", [])
        )

        print("\n" + "=" * 64)
        print("PIPELINE SUMMARY")
        print("=" * 64)
        print(f"Total processed: {len(results)}")

        print("\nOutcome distribution:")
        for s, c in sorted(statuses.items()):
            bar = "█" * (c // 3)
            print(f"  {s:<30} {c:>3}  {bar}")

        print("\nEscalation frequency:")
        for r, c in rules.most_common():
            print(f"  {r:<20} {c:>3}")

        nlp_used = sum(1 for r in results if r.get("_pipeline", {}).get("nlp_enabled"))
        print(f"\nNLP layer used in: {nlp_used}/{len(results)} requests")

        nlp_contra = sum(
            r.get("audit_trail", {}).get("nlp_contradictions_detected", 0)
            for r in results
        )
        print(f"NLP contradictions detected: {nlp_contra}")

        cap_flags = sum(
            1 for r in results
            if any(s.get("capacity_flag") for s in r.get("supplier_shortlist", []))
        )
        print(f"Capacity flags: {cap_flags}")
        print("=" * 64)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _lead_time_score(lead_time_days: float) -> float:
    """
    Convert lead time to a 0–1 score (lower days = higher score).
    Uses an exponential decay: score = exp(-days / 30)
    """
    import math
    return math.exp(-max(0, lead_time_days) / 30.0)


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="ChainIQ Procurement Agent Pipeline"
    )
    parser.add_argument("--n",            type=int,   default=None,
                        help="Process only first N requests")
    parser.add_argument("--id",           type=str,   default=None,
                        help="Process a single request by ID")
    parser.add_argument("--no-nlp",       action="store_true",
                        help="Disable NLP extraction layer")
    parser.add_argument("--no-rationale", action="store_true",
                        help="Disable rationale generation layer")
    parser.add_argument("--refresh",      action="store_true",
                        help="Ignore caches and re-run all layers")
    parser.add_argument("--out",          type=str,   default="../data/output_final.json",
                        help="Output file path")
    args = parser.parse_args()

    pipe = Pipeline(
        data_dir=DATA_DIR,
        enable_nlp=not args.no_nlp,
        enable_rationale=not args.no_rationale,
        force_refresh=args.refresh,
    )

    reqs = json.loads((DATA_DIR / "../data/requests.json").read_text())

    if args.id:
        req = next((r for r in reqs if r["request_id"] == args.id), None)
        if not req:
            print(f"Request {args.id} not found.")
            return
        result = pipe.run(req)
        out_path = DATA_DIR / f"../data/output_{args.id}.json"
        out_path.write_text(json.dumps(result, indent=2, default=str))
        print(f"\nSaved → {out_path}")
        print(f"Status: {result['recommendation']['status']}")
        print(f"Escalations: {len(result.get('escalations', []))}")
        print(f"Shortlist: {len(result.get('supplier_shortlist', []))} suppliers")
        for s in result.get("supplier_shortlist", []):
            print(f"  [{s['rank']}] {s['supplier_name']} | "
                  f"score={s['score']} | "
                  f"note={s.get('recommendation_note','')[:80]}")
        reason = result["recommendation"].get("reason", "")
        if reason:
            print(f"\nRecommendation: {reason}")
        return

    if args.n:
        reqs = reqs[:args.n]

    pipe.run_batch(reqs, output_path=DATA_DIR / args.out)


if __name__ == "__main__":
    main()
