"""
rationale_generator.py  — ChainIQ START Hack 2026
==================================================
Uses Claude to generate human-readable, audit-quality rationale text for
each sourcing decision produced by the rule engine.

WHY A SECOND LLM CALL (not just structured JSON)
-------------------------------------------------
The rule engine produces correct structured data, but auditors need prose
that connects the numbers to procurement logic in plain language.
The example_output.json shows that every supplier entry needs a
`recommendation_note` and the overall recommendation needs a `reason`
paragraph — neither can be templated reliably at scale.

This module:
  1. Takes rule engine output (one processed request)
  2. Feeds the structured facts + few-shot examples from historical awards
  3. Returns per-supplier recommendation_notes and an overall summary
  4. Merges these back into the rule engine output

DESIGN CONSTRAINTS
------------------
  • The LLM is told exactly what facts to use — it cannot invent numbers
  • Few-shot examples are pulled from historical_awards.csv decision_rationale
  • Output is schema-validated before merging — bad JSON triggers retry
  • One API call per request (not per supplier)

INTEGRATION
-----------
  from rationale_generator import RationaleGenerator
  gen = RationaleGenerator()
  output_with_rationale = gen.add_rationale(rule_engine_output)

The pipeline.py calls this after rule_engine_v3.process().
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import google.generativeai as genai
import pandas as pd
from dotenv import load_dotenv

_ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

MODEL      = "gemini-2.5-pro"
MAX_TOKENS = 1200
CACHE_PATH = Path(__file__).parent / "../data/rationale_cache.json"


# ══════════════════════════════════════════════════════════════════════════════
# 1.  FEW-SHOT EXAMPLE BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def build_few_shot_examples(awards: pd.DataFrame, category_l2: str, n: int = 3) -> str:
    """
    Pull real decision rationale from historical awards for the same category.
    Falls back to cross-category examples if not enough same-category records.
    """
    same_cat = awards[
        (awards["category_l2"] == category_l2) & (awards["awarded"] == True)
    ].head(n)

    cross_cat = awards[
        (awards["category_l2"] != category_l2) & (awards["awarded"] == True)
    ].sample(min(n, len(awards)), random_state=42).head(n)

    examples = list(same_cat.itertuples()) + list(cross_cat.itertuples())
    examples = examples[:n]

    lines = []
    for ex in examples:
        lines.append(
            f'  Supplier: {ex.supplier_name} | Rank: {ex.award_rank} | '
            f'Savings: {ex.savings_pct:.1f}% | Lead time: {ex.lead_time_days}d | '
            f'Risk at award: {ex.risk_score_at_award} | '
            f'Rationale: "{ex.decision_rationale}"'
        )
    return "\n".join(lines) if lines else "  (no historical examples available)"


# ══════════════════════════════════════════════════════════════════════════════
# 2.  PROMPT BUILDER
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """\
You are a senior procurement analyst writing audit-ready sourcing rationale.
Your output must be factual, concise, and directly reference the data provided.
Never invent numbers. Never use vague language like "appears to" or "seems".
Write as a procurement professional, not a chatbot.
Respond ONLY with the JSON object specified. No markdown, no preamble."""


def build_rationale_prompt(engine_output: dict, few_shot_examples: str) -> str:
    req  = engine_output.get("request_interpretation", {})
    pol  = engine_output.get("policy_evaluation", {})
    tier = pol.get("approval_threshold", {})
    sups = engine_output.get("supplier_shortlist", [])
    excl = engine_output.get("suppliers_excluded", [])
    escs = engine_output.get("escalations", [])
    rec  = engine_output.get("recommendation", {})
    nlp  = engine_output.get("audit_trail", {})

    # Compact supplier summary for the prompt
    sup_lines = []
    for s in sups:
        fx_note = ""
        if s.get("fx_applied"):
            fx_note = f" [FX {s['pricing_currency']}→{s['req_currency']} @{s.get('fx_rate')}]"
        sup_lines.append(
            f"  Rank {s['rank']}: {s['supplier_name']}"
            f" | preferred={s['preferred']} incumbent={s['incumbent']}"
            f" | unit={s['unit_price']} {s['pricing_currency']}"
            f" | total={s['total_price_in_req_currency']} {s['req_currency']}{fx_note}"
            f" | lead_time={s['lead_time_days']}d (feasible={s['lead_time_feasible']})"
            f" | budget_ok={s['budget_sufficient']}"
            f" | quality={s['quality_score']} risk={s['risk_score']} esg={s['esg_score']}"
            f" | score={s['score']}"
        )

    excl_lines = [
        f"  {e.get('supplier_id','?')} {e.get('supplier_name','?')}: {e['reason'][:80]}"
        for e in excl[:5]
    ]
    esc_lines = [
        f"  {e['rule']} (blocking={e.get('blocking')}): {e['trigger'][:100]}"
        for e in escs
    ]

    return f"""Write procurement rationale for this sourcing decision.

REQUEST CONTEXT:
  Category: {req.get('category_l1')} / {req.get('category_l2')}
  Quantity: {req.get('quantity')} {req.get('unit_of_measure','')}
  Budget: {req.get('budget_amount')} {req.get('currency')}
  Delivery region: {req.get('delivery_region')} | Countries: {req.get('delivery_countries')}
  Required by: {req.get('required_by_date')} ({req.get('days_until_required')} days)
  ESG required: {req.get('esg_requirement')} | Data residency: {req.get('data_residency_required')}
  Preferred supplier (stated): {req.get('preferred_supplier_stated')}
  Incumbent: {req.get('incumbent_supplier')}
  Expedited delivery required: {req.get('expedited_delivery_required')}

POLICY:
  Approval tier: {tier.get('tier_id')} | Quotes required: {tier.get('quotes_required')}
  Fast-track: {tier.get('fast_track_applied')} | FX notes: {tier.get('fx_conversion_notes','')}

SHORTLISTED SUPPLIERS ({len(sups)}):
{chr(10).join(sup_lines) if sup_lines else '  (none)'}

EXCLUDED SUPPLIERS ({len(excl)}):
{chr(10).join(excl_lines) if excl_lines else '  (none)'}

ESCALATIONS ({len(escs)}):
{chr(10).join(esc_lines) if escs else '  (none)'}

OVERALL STATUS: {rec.get('status')}

HISTORICAL EXAMPLES (same or similar category — use as tone/style reference only):
{few_shot_examples}

Return ONLY this JSON (no markdown):
{{
  "supplier_notes": {{
    "<supplier_name_rank1>": "<1-2 sentence factual note explaining rank 1 placement>",
    "<supplier_name_rank2>": "<1-2 sentence factual note>",
    "<supplier_name_rank3>": "<1-2 sentence factual note if present>"
  }},
  "excluded_summary": "<1 sentence summarising why excluded suppliers were dropped, naming the key reasons>",
  "recommendation_reason": "<2-3 sentences: overall decision status, what is blocking or enabling it, what the human reviewer must do next>",
  "preferred_supplier_rationale": "<1-2 sentences on the stated preferred supplier — eligible/not eligible and why, or null if none stated>"
}}

Rules:
- supplier_notes must use the EXACT supplier names from the shortlist above
- Every number you cite must match the data above exactly — do not round or estimate
- If status is cannot_proceed, the recommendation_reason must name every blocking escalation
- If shortlist is empty, supplier_notes should be an empty object {{}}"""


# ══════════════════════════════════════════════════════════════════════════════
# 3.  API CALL + RETRY
# ══════════════════════════════════════════════════════════════════════════════

def _call_rationale_api(prompt: str, model: genai.GenerativeModel) -> dict:
    """Call Gemini and parse the rationale JSON. Retries twice on bad JSON."""
    for attempt in range(3):
        full_prompt = SYSTEM_PROMPT + "\n\n" + prompt
        response = model.generate_content(
            full_prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=MAX_TOKENS,
                temperature=0.0,
            ),
        )
        raw = response.text.strip()
        raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
        raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            if attempt == 2:
                raise ValueError(f"Failed to parse rationale JSON after 3 attempts:\n{raw[:400]}")
            time.sleep(1)
    raise RuntimeError("Unreachable")


# ══════════════════════════════════════════════════════════════════════════════
# 4.  MERGE INTO ENGINE OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

def _merge_rationale(engine_output: dict, rationale: dict) -> dict:
    """
    Inject rationale text back into the rule engine output structure,
    matching the example_output.json format exactly.
    """
    out = json.loads(json.dumps(engine_output))  # deep copy

    supplier_notes = rationale.get("supplier_notes", {})
    for s in out.get("supplier_shortlist", []):
        name = s["supplier_name"]
        s["recommendation_note"] = supplier_notes.get(name, "")

    if excl_summary := rationale.get("excluded_summary"):
        for e in out.get("suppliers_excluded", []):
            if "summary" not in e:
                e["summary"] = excl_summary

    out["recommendation"]["reason"] = rationale.get(
        "recommendation_reason", ""
    )

    pref_rationale = rationale.get("preferred_supplier_rationale")
    if pref_rationale:
        out["recommendation"]["preferred_supplier_rationale"] = pref_rationale

    return out


# ══════════════════════════════════════════════════════════════════════════════
# 5.  MAIN CLASS
# ══════════════════════════════════════════════════════════════════════════════

class RationaleGenerator:
    """
    Adds LLM-generated rationale text to rule engine output.

    Usage:
        gen = RationaleGenerator()
        enriched = gen.add_rationale(engine_output)
    """

    def __init__(
        self,
        api_key: str | None = None,
        awards_path: Path | str = "historical_awards.csv",
        cache_path: Path = CACHE_PATH,
        inter_request_delay: float = 0.3,
    ):
        key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise EnvironmentError(
                "GOOGLE_API_KEY not set. "
                "Add GOOGLE_API_KEY=<your-key> to the backend .env file."
            )
        genai.configure(api_key=key)
        self.model = genai.GenerativeModel(MODEL)
        self.awards = pd.read_csv(awards_path)
        self.cache_path = cache_path
        self.delay = inter_request_delay
        self._cache: dict = self._load_cache()

    def _load_cache(self) -> dict:
        if self.cache_path.exists():
            try:
                return json.loads(self.cache_path.read_text())
            except Exception:
                return {}
        return {}

    def _save_cache(self) -> None:
        self.cache_path.write_text(json.dumps(self._cache, indent=2))

    # ─────────────────────────────────────────────────────────────────────────

    def add_rationale(
        self,
        engine_output: dict,
        force_refresh: bool = False,
    ) -> dict:
        """
        Add recommendation_note to each shortlisted supplier and a
        recommendation.reason string to the overall output.

        If the shortlist is empty, generates an explanation of why no
        compliant supplier was found from the escalation data.
        """
        req_id = engine_output.get("request_id", "unknown")
        cache_key = f"rationale_{req_id}"

        if not force_refresh and cache_key in self._cache:
            cached = self._cache[cache_key]
            return _merge_rationale(engine_output, cached)

        category_l2 = engine_output.get(
            "request_interpretation", {}
        ).get("category_l2", "")
        few_shot = build_few_shot_examples(self.awards, category_l2)
        prompt   = build_rationale_prompt(engine_output, few_shot)

        try:
            rationale = _call_rationale_api(prompt, self.model)
            self._cache[cache_key] = rationale
            self._save_cache()
        except Exception as e:
            # Graceful fallback — use template strings
            rationale = _template_fallback(engine_output, str(e))

        return _merge_rationale(engine_output, rationale)

    # ─────────────────────────────────────────────────────────────────────────

    def add_rationale_batch(
        self,
        engine_outputs: list[dict],
        force_refresh: bool = False,
        verbose: bool = True,
    ) -> list[dict]:
        """Add rationale to a list of engine outputs."""
        results = []
        for i, out in enumerate(engine_outputs):
            req_id = out.get("request_id", "?")
            is_cached = (
                not force_refresh
                and f"rationale_{req_id}" in self._cache
            )
            try:
                enriched = self.add_rationale(out, force_refresh=force_refresh)
                results.append(enriched)
                if verbose and not is_cached:
                    n_sup = len(out.get("supplier_shortlist", []))
                    print(f"  [{i+1:3d}/{len(engine_outputs)}] {req_id} "
                          f"suppliers={n_sup} status={out['recommendation']['status']}")
            except Exception as e:
                if verbose:
                    print(f"  [{i+1:3d}/{len(engine_outputs)}] {req_id} ERROR: {e}")
                results.append(out)

            if not is_cached and i < len(engine_outputs) - 1:
                time.sleep(self.delay)

        return results


# ══════════════════════════════════════════════════════════════════════════════
# 6.  TEMPLATE FALLBACK
# ══════════════════════════════════════════════════════════════════════════════

def _template_fallback(engine_output: dict, error_msg: str) -> dict:
    """
    Generate minimal rationale without an API call.
    Used when the API fails — ensures the pipeline never breaks.
    """
    sups = engine_output.get("supplier_shortlist", [])
    escs = engine_output.get("escalations", [])
    status = engine_output.get("recommendation", {}).get("status", "unknown")

    supplier_notes = {}
    for s in sups:
        name = s["supplier_name"]
        parts = []
        if s.get("preferred"):
            parts.append("Preferred supplier")
        if s.get("incumbent"):
            parts.append("incumbent")
        parts.append(
            f"total {s['total_price_in_req_currency']} {s['req_currency']}"
        )
        if not s.get("lead_time_feasible"):
            parts.append(f"lead time {s['lead_time_days']}d infeasible")
        if not s.get("budget_sufficient"):
            parts.append("over budget")
        supplier_notes[name] = f"Rank {s['rank']}: " + "; ".join(parts) + "."

    if status == "cannot_proceed":
        blocking = [e["trigger"][:80] for e in escs if e.get("blocking")]
        reason = "Cannot proceed: " + " | ".join(blocking) if blocking else "Blocking issues require resolution."
    elif not sups:
        reason = "No compliant supplier identified for this category and region."
    else:
        top = sups[0]
        reason = (
            f"Recommended: {top['supplier_name']} at "
            f"{top['total_price_in_req_currency']} {top['req_currency']} "
            f"(rank 1 by composite score {top['score']})."
        )

    return {
        "supplier_notes": supplier_notes,
        "excluded_summary": f"Suppliers excluded due to policy, geography, capacity, or MOQ constraints. (Rationale API error: {error_msg[:80]})",
        "recommendation_reason": reason,
        "preferred_supplier_rationale": None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 7.  ENTRY POINT (test single request)
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    from pathlib import Path
    from rule_engine_v3 import ProcurementRuleEngine

    base = Path(__file__).parent
    reqs = json.loads((base / "../data/requests.json").read_text())

    # Test on REQ-000004 (contradictory, well-known example)
    req = next(r for r in reqs if r["request_id"] == "REQ-000004")
    engine = ProcurementRuleEngine(data_dir=base)
    engine_out = engine.process(req)

    gen = RationaleGenerator(
        awards_path=base / "../data/historical_awards.csv",
        cache_path=base / "../data/rationale_cache.json",
    )
    final = gen.add_rationale(engine_out)

    print(f"\n=== REQ-000004 — with rationale ===")
    print(f"Status: {final['recommendation']['status']}")
    print(f"\nRecommendation reason:\n  {final['recommendation'].get('reason','')}")
    print("\nSupplier notes:")
    for s in final["supplier_shortlist"]:
        print(f"  [{s['rank']}] {s['supplier_name']}: {s.get('recommendation_note','')}")
    pref_rat = final["recommendation"].get("preferred_supplier_rationale")
    if pref_rat:
        print(f"\nPreferred supplier rationale:\n  {pref_rat}")
