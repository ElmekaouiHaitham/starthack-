"""
nlp_extractor.py  — ChainIQ START Hack 2026
=============================================
LLM-powered extraction layer that sits BEFORE the deterministic rule engine.

WHAT THIS MODULE DOES (and what it deliberately does NOT do)
------------------------------------------------------------
DOES:
  • Detects the actual language of request_text and translates to English
  • Extracts quantity, budget, currency as they appear in the free text
    (context-aware: ignores dates, IDs, reference numbers)
  • Extracts the "total rollout" vs "per-location" quantity when both appear
  • Identifies policy-refusal phrases ("no exception", "skip tender", etc.)
  • Identifies specific product/model mentions (e.g. "MacBook Pro 16-inch")
  • Extracts ESG and data residency signals from text
  • Detects urgency language

DOES NOT:
  • Apply procurement policy rules  ← that is the rule engine's job
  • Make supplier recommendations
  • Evaluate compliance
  • Judge whether a request is valid

The output of this module enriches the request dict with an `nlp` key.
The rule engine reads that key to detect contradictions and set flags.

INTEGRATION
-----------
  from nlp_extractor import NLPExtractor
  extractor = NLPExtractor()
  enriched  = extractor.enrich(request)      # single request
  # or
  enriched_batch = extractor.enrich_batch(requests)  # all 304

Then pass enriched requests to rule_engine_v3.ProcurementRuleEngine.process().

SETUP
-----
  Set GOOGLE_API_KEY in the .env file located at the project backend root.
  pip install google-generativeai python-dotenv

CACHING
-------
  Results are cached in ./nlp_cache.json.
  Delete the file or set force_refresh=True to re-run.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import google.generativeai as genai
from dotenv import load_dotenv

# Load .env from the backend root (two levels up from this notebook directory)
_ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

# ══════════════════════════════════════════════════════════════════════════════
# 0.  CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

MODEL = "gemini-2.5-pro"
MAX_TOKENS = 800
CACHE_PATH = Path(__file__).parent / "nlp_cache.json"

# Fraction thresholds for contradiction detection
QTY_MISMATCH_THRESHOLD    = 0.10   # 10% diff between text qty and field qty
BUDGET_MISMATCH_THRESHOLD = 0.05   # 5% diff between text budget and field budget

# Rate limiting between API calls (seconds)
INTER_REQUEST_DELAY = 0.3


# ══════════════════════════════════════════════════════════════════════════════
# 1.  EXTRACTION SCHEMA
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class PolicyRefusal:
    """A detected attempt to bypass a procurement policy step."""
    refusal_type: str          # "no_exception_mandate" | "skip_competitive_tender"
                               # | "single_supplier_waiver" | "waive_review"
    phrase: str                # exact phrase found in text
    applies_to: str            # what the requester is refusing


@dataclass
class TextExtraction:
    """
    All information extracted from request_text by the LLM.
    Every field that cannot be reliably extracted is None.
    """
    # Language
    detected_language: str              # ISO 639-1: "en", "fr", "de", "es", "pt", "ja"
    english_translation: str | None     # None if already English

    # Quantity signals from text
    qty_primary: float | None           # main procurement quantity
    qty_primary_unit: str | None        # "devices", "days", "months", "instances", etc.
    qty_total_rollout: float | None     # total rollout qty if different from per-location
    qty_ambiguity_note: str | None      # human note if multiple conflicting qty signals

    # Budget signals from text
    budget_extracted: float | None
    budget_currency: str | None         # "EUR" | "CHF" | "USD" | None

    # Supplier signals
    preferred_supplier_in_text: str | None  # supplier name as written in text

    # Policy refusal
    policy_refusal: PolicyRefusal | None

    # Specification
    spec_mentioned: str | None          # e.g. "MacBook Pro 16-inch", "IP65+ rugged device"
    spec_implies_higher_cost: bool      # True if spec likely implies cost > budget

    # Soft signals
    esg_signal_in_text: bool
    data_residency_signal_in_text: bool
    urgency_level: str                  # "standard" | "urgent" | "critical"
    key_constraints: list[str]          # quoted short constraints from text


@dataclass
class Contradiction:
    """A detected discrepancy between extracted text content and structured fields."""
    contradiction_id: str
    contradiction_type: str    # see CONTRADICTION_TYPES below
    severity: str              # "critical" | "high" | "warning"
    field_value: Any
    text_value: Any
    description: str
    recommended_action: str


# All possible contradiction types
CONTRADICTION_TYPES = {
    "QUANTITY_MISMATCH":          "Numeric quantity in text differs from quantity field by >10%",
    "BUDGET_MISMATCH":            "Budget stated in text differs from budget_amount field",
    "POLICY_REFUSAL_SINGLE_SUP":  "Text requests single-supplier or no-exception selection",
    "POLICY_REFUSAL_SKIP_TENDER": "Text requests to skip competitive tender",
    "SPEC_BUDGET_GAP":            "Specific product/model mentioned likely costs more than budget",
    "ROLLOUT_QTY_AMBIGUITY":      "Text contains both per-location and total rollout quantities",
    "PREFERRED_SUPPLIER_MISMATCH":"Supplier named in text differs from preferred_supplier_mentioned field",
    "LANGUAGE_MISMATCH":          "request_language field does not match detected text language",
}


@dataclass
class NLPResult:
    """Full output of the NLP pipeline for one request."""
    request_id: str
    extraction: TextExtraction
    contradictions: list[Contradiction]
    processing_notes: list[str] = field(default_factory=list)
    cache_hit: bool = False


# ══════════════════════════════════════════════════════════════════════════════
# 2.  EXTRACTION PROMPT
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are a procurement data extraction specialist.
Your only job is to extract structured facts from purchase request text.
You do NOT evaluate compliance, apply policy rules, or make recommendations.

You MUST respond with valid JSON matching exactly the schema provided.
No markdown, no explanation, no preamble — only the JSON object.

CRITICAL EXTRACTION RULES:
1. QUANTITY: Extract the main procurement quantity. Ignore years (2026), IDs, and percentages.
   If text says "25 engineers × 60 days", qty_primary=1500 (the actual effort days), not 25.
   If text says "24 months" for a subscription, qty_primary=24, qty_primary_unit="months".
   If text says "rollout spans X and total quantity is Y", qty_total_rollout=Y.

2. BUDGET: Extract the budget amount as a plain float. 
   Handle all formats: "1 320 000.00", "1,320,000", "CHF 432'000", "360.000 EUR" (European dot=thousands).
   European format: "360.000" = 360000 (dot is thousands separator), "360,00" = 360.0 (comma is decimal).
   Swiss format: "432'000" = 432000.

3. POLICY REFUSAL: Flag these specific patterns:
   - "no exception" / "without exception" → "no_exception_mandate"
   - "without competitive tender" / "skip tender" / "no competitive process" → "skip_competitive_tender"
   - "single supplier" / "sole source" (when phrased as a mandate, not a preference) → "single_supplier_waiver"
   - "waive [review/process]" → "waive_review"
   A preference ("prefer X") is NOT a refusal. Only flag explicit bypass attempts.

4. LANGUAGE: Detect the actual language of the text content, not the lang field.
   If not English, provide a complete English translation in english_translation.

5. SPEC: Only capture truly specific product specifications (model names, technical standards like IP65).
   "premium specification" is NOT a specific spec — leave spec_mentioned null."""

def build_user_prompt(request: dict) -> str:
    text = request.get("request_text", "")
    lang_field = request.get("request_language", "en")
    qty_field = request.get("quantity")
    budget_field = request.get("budget_amount")
    currency_field = request.get("currency", "EUR")
    pref_field = request.get("preferred_supplier_mentioned")

    return f"""Extract structured data from this procurement request.

REQUEST TEXT:
{text}

STRUCTURED FIELD VALUES (for reference only — do not copy these into your extraction):
  request_language field: {lang_field}
  quantity field: {qty_field}
  budget_amount field: {budget_field} {currency_field}
  preferred_supplier_mentioned field: {pref_field}

Return ONLY this JSON object (no markdown, no comments):
{{
  "detected_language": "<ISO 639-1 code of the actual text language>",
  "english_translation": "<full English translation if not English, else null>",
  "qty_primary": <float or null>,
  "qty_primary_unit": "<unit string or null>",
  "qty_total_rollout": <float or null — only if text has both per-location AND total quantities>,
  "qty_ambiguity_note": "<explain if multiple conflicting qty signals, else null>",
  "budget_extracted": <float or null>,
  "budget_currency": "<EUR|CHF|USD or null>",
  "preferred_supplier_in_text": "<exact supplier name from text or null>",
  "policy_refusal": {{
    "refusal_type": "<no_exception_mandate|skip_competitive_tender|single_supplier_waiver|waive_review>",
    "phrase": "<exact phrase from text>",
    "applies_to": "<what is being refused>"
  }} or null,
  "spec_mentioned": "<specific product model or technical standard, else null>",
  "spec_implies_higher_cost": <true|false>,
  "esg_signal_in_text": <true|false>,
  "data_residency_signal_in_text": <true|false>,
  "urgency_level": "<standard|urgent|critical>",
  "key_constraints": ["<short constraint 1>", "<short constraint 2>"]
}}"""


# ══════════════════════════════════════════════════════════════════════════════
# 3.  API CLIENT
# ══════════════════════════════════════════════════════════════════════════════

def call_extraction_api(request: dict, model: genai.GenerativeModel) -> dict:
    """
    Call Gemini API and return the raw parsed JSON dict.
    Raises ValueError if the response is not valid JSON.
    """
    full_prompt = SYSTEM_PROMPT + "\n\n" + build_user_prompt(request)
    response = model.generate_content(
        full_prompt,
        generation_config=genai.types.GenerationConfig(
            max_output_tokens=MAX_TOKENS,
            temperature=0.0,
        ),
    )
    raw_text = response.text.strip()

    # Strip any accidental markdown fences
    raw_text = re.sub(r'^```(?:json)?\s*', '', raw_text, flags=re.MULTILINE)
    raw_text = re.sub(r'\s*```$', '', raw_text, flags=re.MULTILINE)

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"API returned invalid JSON: {e}\nRaw response:\n{raw_text[:500]}"
        )


def parse_extraction(raw: dict) -> TextExtraction:
    """Convert raw API dict into a typed TextExtraction dataclass."""
    refusal_raw = raw.get("policy_refusal")
    refusal = None
    if refusal_raw and isinstance(refusal_raw, dict):
        refusal = PolicyRefusal(
            refusal_type=refusal_raw.get("refusal_type", "unknown"),
            phrase=refusal_raw.get("phrase", ""),
            applies_to=refusal_raw.get("applies_to", ""),
        )

    return TextExtraction(
        detected_language=raw.get("detected_language", "en"),
        english_translation=raw.get("english_translation"),
        qty_primary=_safe_float(raw.get("qty_primary")),
        qty_primary_unit=raw.get("qty_primary_unit"),
        qty_total_rollout=_safe_float(raw.get("qty_total_rollout")),
        qty_ambiguity_note=raw.get("qty_ambiguity_note"),
        budget_extracted=_safe_float(raw.get("budget_extracted")),
        budget_currency=raw.get("budget_currency"),
        preferred_supplier_in_text=raw.get("preferred_supplier_in_text"),
        policy_refusal=refusal,
        spec_mentioned=raw.get("spec_mentioned"),
        spec_implies_higher_cost=bool(raw.get("spec_implies_higher_cost", False)),
        esg_signal_in_text=bool(raw.get("esg_signal_in_text", False)),
        data_residency_signal_in_text=bool(raw.get("data_residency_signal_in_text", False)),
        urgency_level=raw.get("urgency_level", "standard"),
        key_constraints=raw.get("key_constraints", []) or [],
    )


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 4.  CONTRADICTION DETECTOR
# ══════════════════════════════════════════════════════════════════════════════

def detect_contradictions(extraction: TextExtraction, request: dict) -> list[Contradiction]:
    """
    Deterministic contradiction detection: compare extraction results against
    the structured fields in the original request.
    No LLM call here — pure Python logic.
    """
    contradictions: list[Contradiction] = []
    cid = 0

    def add(ctype: str, severity: str, field_val: Any, text_val: Any, desc: str, action: str):
        nonlocal cid
        cid += 1
        contradictions.append(Contradiction(
            contradiction_id=f"C-{cid:03d}",
            contradiction_type=ctype,
            severity=severity,
            field_value=field_val,
            text_value=text_val,
            description=desc,
            recommended_action=action,
        ))

    qty_field   = request.get("quantity")
    budget_field = request.get("budget_amount")
    ccy_field   = request.get("currency", "EUR")
    pref_field  = request.get("preferred_supplier_mentioned")
    lang_field  = request.get("request_language", "en")

    # ── C1: QUANTITY MISMATCH ────────────────────────────────────────────────
    if extraction.qty_primary is not None and qty_field is not None:
        diff = abs(extraction.qty_primary - float(qty_field)) / max(float(qty_field), 1)
        if diff > QTY_MISMATCH_THRESHOLD:
            add(
                "QUANTITY_MISMATCH", "critical",
                qty_field, extraction.qty_primary,
                (
                    f"Field quantity={qty_field} {extraction.qty_primary_unit or ''}, "
                    f"but text implies {extraction.qty_primary} {extraction.qty_primary_unit or ''}. "
                    f"Difference: {diff*100:.0f}%."
                    + (f" {extraction.qty_ambiguity_note}" if extraction.qty_ambiguity_note else "")
                ),
                "Confirm actual quantity with requester before pricing (ER-001).",
            )

    # ── C2: ROLLOUT QTY AMBIGUITY ────────────────────────────────────────────
    if extraction.qty_total_rollout is not None and extraction.qty_primary is not None:
        if abs(extraction.qty_total_rollout - extraction.qty_primary) / max(extraction.qty_primary, 1) > 0.10:
            add(
                "ROLLOUT_QTY_AMBIGUITY", "high",
                extraction.qty_primary, extraction.qty_total_rollout,
                (
                    f"Text contains both per-location quantity ({extraction.qty_primary}) "
                    f"and total rollout quantity ({extraction.qty_total_rollout}). "
                    f"Pricing should be based on the total rollout for tier selection."
                    + (f" {extraction.qty_ambiguity_note}" if extraction.qty_ambiguity_note else "")
                ),
                "Use total rollout quantity for pricing tier selection. Confirm delivery scope.",
            )

    # ── C3: BUDGET MISMATCH ──────────────────────────────────────────────────
    if extraction.budget_extracted is not None and budget_field is not None:
        # Currency match check
        ccy_match = (extraction.budget_currency is None or
                     extraction.budget_currency == ccy_field)
        if ccy_match:
            diff = abs(extraction.budget_extracted - float(budget_field)) / max(float(budget_field), 1)
            if diff > BUDGET_MISMATCH_THRESHOLD:
                add(
                    "BUDGET_MISMATCH", "critical",
                    f"{budget_field} {ccy_field}",
                    f"{extraction.budget_extracted} {extraction.budget_currency}",
                    (
                        f"Field budget={budget_field} {ccy_field}, but text states "
                        f"{extraction.budget_extracted} {extraction.budget_currency}. "
                        f"Difference: {diff*100:.0f}%."
                    ),
                    "Requester must confirm the authorised budget amount before award (ER-001).",
                )
        else:
            add(
                "BUDGET_MISMATCH", "high",
                f"{budget_field} {ccy_field}",
                f"{extraction.budget_extracted} {extraction.budget_currency}",
                (
                    f"Budget currency mismatch: field shows {ccy_field} but text uses "
                    f"{extraction.budget_currency}."
                ),
                "Confirm currency alignment with requester.",
            )

    # ── C4: POLICY REFUSAL — no exception / skip tender ──────────────────────
    if extraction.policy_refusal is not None:
        rt = extraction.policy_refusal.refusal_type

        if rt == "no_exception_mandate":
            add(
                "POLICY_REFUSAL_SINGLE_SUP", "critical",
                "procurement policy (multi-quote requirement)",
                extraction.policy_refusal.phrase,
                (
                    f"Requester instruction '{extraction.policy_refusal.phrase}' mandates "
                    f"single-supplier selection and prohibits exceptions. This may conflict "
                    f"with approval-threshold requirements for multiple quotes."
                ),
                "Policy cannot be waived unilaterally by requester. Deviation requires Procurement Manager approval.",
            )

        elif rt == "skip_competitive_tender":
            add(
                "POLICY_REFUSAL_SKIP_TENDER", "critical",
                "procurement policy (competitive tender requirement)",
                extraction.policy_refusal.phrase,
                (
                    f"Requester instruction '{extraction.policy_refusal.phrase}' requests "
                    f"bypassing competitive tender. This directly conflicts with policy for "
                    f"contracts requiring multiple quotes."
                ),
                "Mandatory competitive process cannot be skipped. Escalate to Procurement Manager.",
            )

        elif rt == "single_supplier_waiver":
            # 'single supplier preferred' is softer — warning not critical
            add(
                "POLICY_REFUSAL_SINGLE_SUP", "warning",
                "procurement policy",
                extraction.policy_refusal.phrase,
                (
                    f"Text expresses single-supplier preference ('{extraction.policy_refusal.phrase}'). "
                    f"This is a preference, not a mandate, but conflicts with any multi-quote requirement."
                ),
                "Note preference in audit trail. Apply required number of quotes per approval tier.",
            )

        elif rt == "waive_review":
            add(
                "POLICY_REFUSAL_SKIP_TENDER", "high",
                "mandatory review process",
                extraction.policy_refusal.phrase,
                f"Text requests waiving a review step: '{extraction.policy_refusal.phrase}'.",
                "Confirm with category manager whether review can be legitimately bypassed.",
            )

    # ── C5: SPEC vs BUDGET GAP ────────────────────────────────────────────────
    if extraction.spec_mentioned and extraction.spec_implies_higher_cost:
        add(
            "SPEC_BUDGET_GAP", "high",
            budget_field,
            extraction.spec_mentioned,
            (
                f"Specific product/model '{extraction.spec_mentioned}' is mentioned. "
                f"This specification likely implies a cost higher than the stated budget "
                f"of {budget_field} {ccy_field}."
            ),
            "Verify that budget covers the stated specification. Requester may need to increase budget or relax spec.",
        )

    # ── C6: PREFERRED SUPPLIER TEXT vs FIELD ─────────────────────────────────
    if (extraction.preferred_supplier_in_text and pref_field and
            extraction.preferred_supplier_in_text.lower() != pref_field.lower()):
        add(
            "PREFERRED_SUPPLIER_MISMATCH", "warning",
            pref_field,
            extraction.preferred_supplier_in_text,
            (
                f"Structured field preferred_supplier_mentioned='{pref_field}' "
                f"but request text names '{extraction.preferred_supplier_in_text}'."
            ),
            "Confirm which supplier the requester intends as preferred.",
        )

    # ── C7: LANGUAGE TAG vs DETECTED LANGUAGE ────────────────────────────────
    detected = extraction.detected_language
    if detected and detected != lang_field:
        add(
            "LANGUAGE_MISMATCH", "warning",
            lang_field,
            detected,
            (
                f"request_language field='{lang_field}' but text is actually in '{detected}'. "
                + (f"Translation: {extraction.english_translation[:100]}..."
                   if extraction.english_translation else "")
            ),
            "Use detected language for NLP processing. The translated text is authoritative.",
        )

    return contradictions


# ══════════════════════════════════════════════════════════════════════════════
# 5.  CACHE
# ══════════════════════════════════════════════════════════════════════════════

def load_cache(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}


def save_cache(cache: dict, path: Path) -> None:
    path.write_text(json.dumps(cache, indent=2, default=str))


def _nlp_result_to_dict(result: NLPResult) -> dict:
    """Serialize NLPResult to a plain dict for caching."""
    d = {
        "request_id": result.request_id,
        "cache_hit": result.cache_hit,
        "processing_notes": result.processing_notes,
        "extraction": asdict(result.extraction),
        "contradictions": [asdict(c) for c in result.contradictions],
    }
    return d


def _nlp_result_from_dict(d: dict) -> NLPResult:
    """Deserialize a cached dict back to NLPResult."""
    ext = d["extraction"]
    pr = ext.get("policy_refusal")
    refusal = PolicyRefusal(**pr) if pr else None
    extraction = TextExtraction(
        detected_language=ext["detected_language"],
        english_translation=ext.get("english_translation"),
        qty_primary=ext.get("qty_primary"),
        qty_primary_unit=ext.get("qty_primary_unit"),
        qty_total_rollout=ext.get("qty_total_rollout"),
        qty_ambiguity_note=ext.get("qty_ambiguity_note"),
        budget_extracted=ext.get("budget_extracted"),
        budget_currency=ext.get("budget_currency"),
        preferred_supplier_in_text=ext.get("preferred_supplier_in_text"),
        policy_refusal=refusal,
        spec_mentioned=ext.get("spec_mentioned"),
        spec_implies_higher_cost=ext.get("spec_implies_higher_cost", False),
        esg_signal_in_text=ext.get("esg_signal_in_text", False),
        data_residency_signal_in_text=ext.get("data_residency_signal_in_text", False),
        urgency_level=ext.get("urgency_level", "standard"),
        key_constraints=ext.get("key_constraints", []),
    )
    contradictions = [Contradiction(**c) for c in d.get("contradictions", [])]
    return NLPResult(
        request_id=d["request_id"],
        extraction=extraction,
        contradictions=contradictions,
        processing_notes=d.get("processing_notes", []),
        cache_hit=d.get("cache_hit", False),
    )


# ══════════════════════════════════════════════════════════════════════════════
# 6.  MAIN EXTRACTOR CLASS
# ══════════════════════════════════════════════════════════════════════════════

class NLPExtractor:
    """
    Main entry point for NLP extraction.

    Usage:
        extractor = NLPExtractor()
        result    = extractor.process(request_dict)
        enriched  = extractor.enrich(request_dict)   # adds nlp key in-place copy
    """

    def __init__(
        self,
        api_key: str | None = None,
        cache_path: Path = CACHE_PATH,
        inter_request_delay: float = INTER_REQUEST_DELAY,
    ):
        key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise EnvironmentError(
                "GOOGLE_API_KEY environment variable not set. "
                "Add GOOGLE_API_KEY=<your-key> to the backend .env file."
            )
        genai.configure(api_key=key)
        self.client = genai.GenerativeModel(MODEL)
        self.cache_path = cache_path
        self.delay = inter_request_delay
        self._cache = load_cache(cache_path)

    # ─────────────────────────────────────────────────────────────────────────
    # Core: process a single request
    # ─────────────────────────────────────────────────────────────────────────

    def process(self, request: dict, force_refresh: bool = False) -> NLPResult:
        """
        Run extraction + contradiction detection for one request.
        Returns NLPResult. Caches result by request_id.
        """
        req_id = request.get("request_id", "unknown")

        # Cache hit
        if not force_refresh and req_id in self._cache:
            result = _nlp_result_from_dict(self._cache[req_id])
            result.cache_hit = True
            return result

        notes: list[str] = []

        # API call with retry on transient errors
        raw = None
        for attempt in range(3):
            try:
                raw = call_extraction_api(request, self.client)
                break
            except Exception as e:
                err_str = str(e)
                # Detect rate-limit / quota errors by message content
                if "quota" in err_str.lower() or "rate" in err_str.lower() or "429" in err_str:
                    wait = 5 * (attempt + 1)
                    notes.append(f"Rate limit hit — waiting {wait}s (attempt {attempt+1})")
                    time.sleep(wait)
                elif isinstance(e, ValueError):
                    notes.append(f"JSON parse error: {err_str[:120]}")
                    if attempt == 2:
                        return _fallback_result(req_id, request, notes)
                else:
                    notes.append(f"API error (attempt {attempt+1}): {err_str[:100]}")
                    if attempt == 2:
                        return _fallback_result(req_id, request, notes)

        if raw is None:
            return _fallback_result(req_id, request, notes)

        extraction = parse_extraction(raw)
        contradictions = detect_contradictions(extraction, request)

        result = NLPResult(
            request_id=req_id,
            extraction=extraction,
            contradictions=contradictions,
            processing_notes=notes,
            cache_hit=False,
        )

        # Save to cache
        self._cache[req_id] = _nlp_result_to_dict(result)
        save_cache(self._cache, self.cache_path)

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Enrich: add nlp key to request dict
    # ─────────────────────────────────────────────────────────────────────────

    def enrich(self, request: dict, force_refresh: bool = False) -> dict:
        """
        Return a copy of request with an 'nlp' key containing NLP results.
        The rule engine reads request['nlp'] to adjust its behaviour.
        """
        result = self.process(request, force_refresh=force_refresh)
        enriched = dict(request)
        enriched["nlp"] = _nlp_result_to_dict(result)

        # Surface contradictions as top-level flags the rule engine checks
        enriched["_nlp_qty_override"] = _nlp_qty_override(result, request)
        enriched["_nlp_policy_refusal"] = (
            asdict(result.extraction.policy_refusal)
            if result.extraction.policy_refusal else None
        )
        enriched["_nlp_translation"] = result.extraction.english_translation
        enriched["_nlp_contradictions"] = [asdict(c) for c in result.contradictions]

        return enriched

    # ─────────────────────────────────────────────────────────────────────────
    # Batch processing
    # ─────────────────────────────────────────────────────────────────────────

    def enrich_batch(
        self,
        requests: list[dict],
        force_refresh: bool = False,
        verbose: bool = True,
    ) -> list[dict]:
        """
        Enrich all requests with NLP results.
        Respects cache — only calls API for uncached requests.
        """
        enriched_all = []
        needs_api = [r for r in requests
                     if force_refresh or r.get("request_id") not in self._cache]
        cached_count = len(requests) - len(needs_api)

        if verbose:
            print(f"NLP batch: {len(requests)} requests "
                  f"({cached_count} cached, {len(needs_api)} need API calls)")

        for i, req in enumerate(requests):
            req_id = req.get("request_id", "?")
            is_api_call = force_refresh or req_id not in self._cache

            try:
                enriched = self.enrich(req, force_refresh=force_refresh)
                enriched_all.append(enriched)
                if verbose and is_api_call:
                    nlp = enriched.get("nlp", {})
                    n_contra = len(nlp.get("contradictions", []))
                    lang = nlp.get("extraction", {}).get("detected_language", "?")
                    print(f"  [{i+1:3d}/{len(requests)}] {req_id} "
                          f"lang={lang} contradictions={n_contra}")
            except Exception as e:
                if verbose:
                    print(f"  [{i+1:3d}/{len(requests)}] {req_id} ERROR: {e}")
                # Append with empty nlp on error
                fallback = dict(req)
                fallback["nlp"] = _nlp_result_to_dict(
                    _fallback_result(req_id, req, [str(e)])
                )
                fallback["_nlp_qty_override"] = None
                fallback["_nlp_policy_refusal"] = None
                fallback["_nlp_translation"] = None
                fallback["_nlp_contradictions"] = []
                enriched_all.append(fallback)

            # Rate limit between API calls
            if is_api_call and i < len(requests) - 1:
                time.sleep(self.delay)

        if verbose:
            total_contra = sum(
                len(r.get("nlp", {}).get("contradictions", []))
                for r in enriched_all
            )
            print(f"NLP complete. Total contradictions found: {total_contra}")

        return enriched_all


# ══════════════════════════════════════════════════════════════════════════════
# 7.  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _nlp_qty_override(result: NLPResult, request: dict) -> dict | None:
    """
    If NLP found a quantity that differs from the field, return the override dict.
    The rule engine uses this to price at the corrected quantity.
    """
    qty_field = request.get("quantity")
    qty_text  = result.extraction.qty_primary
    if qty_text is None:
        return None
    if qty_field is None:
        return {
            "qty_from_text": qty_text,
            "unit": result.extraction.qty_primary_unit,
            "source": "text_only",
            "note": "Quantity field was null; extracted from text.",
        }
    diff = abs(qty_text - float(qty_field)) / max(float(qty_field), 1)
    if diff > QTY_MISMATCH_THRESHOLD:
        return {
            "qty_field": float(qty_field),
            "qty_from_text": qty_text,
            "unit": result.extraction.qty_primary_unit,
            "diff_pct": round(diff * 100, 1),
            "source": "text_override",
            "note": "Text quantity used for pricing; field value flagged as contradictory.",
        }
    return None


def _fallback_result(req_id: str, request: dict, notes: list[str]) -> NLPResult:
    """
    Return a safe empty NLPResult when the API fails.
    The rule engine can still proceed using structured fields only.
    """
    empty_extraction = TextExtraction(
        detected_language=request.get("request_language", "en"),
        english_translation=None,
        qty_primary=None,
        qty_primary_unit=None,
        qty_total_rollout=None,
        qty_ambiguity_note=None,
        budget_extracted=None,
        budget_currency=None,
        preferred_supplier_in_text=None,
        policy_refusal=None,
        spec_mentioned=None,
        spec_implies_higher_cost=False,
        esg_signal_in_text=False,
        data_residency_signal_in_text=False,
        urgency_level="standard",
        key_constraints=[],
    )
    return NLPResult(
        request_id=req_id,
        extraction=empty_extraction,
        contradictions=[],
        processing_notes=notes + ["FALLBACK: API failed; NLP fields empty."],
        cache_hit=False,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 8.  RULE ENGINE INTEGRATION PATCH
# ══════════════════════════════════════════════════════════════════════════════

def apply_nlp_to_rule_engine_input(enriched_request: dict) -> dict:
    """
    Post-process an enriched request so the rule engine uses NLP findings.

    The rule engine (rule_engine_v3.py) reads these standard fields:
      quantity, budget_amount, currency, esg_requirement,
      data_residency_constraint, preferred_supplier_mentioned

    This function patches those fields with NLP-extracted values
    when a reliable override exists, and adds _nlp_* flags.

    The rule engine's process() method is responsible for surfacing
    any _nlp_contradictions in its validation section.
    """
    req = dict(enriched_request)
    nlp = req.get("nlp", {})
    ext = nlp.get("extraction", {})

    # 1. Use NLP translation as the working text
    if ext.get("english_translation"):
        req["_working_text"] = ext["english_translation"]
    else:
        req["_working_text"] = req.get("request_text", "")

    # 2. Escalate esg and data_residency if NLP found signals the structured field missed
    if ext.get("esg_signal_in_text") and not req.get("esg_requirement"):
        req["esg_requirement"] = True
        req["_nlp_esg_override"] = "NLP detected ESG language not captured in structured field"

    if ext.get("data_residency_signal_in_text") and not req.get("data_residency_constraint"):
        req["data_residency_constraint"] = True
        req["_nlp_data_residency_override"] = (
            "NLP detected data residency language not captured in structured field"
        )

    # 3. If quantity was null but NLP extracted one, fill it in
    if req.get("quantity") is None and ext.get("qty_primary") is not None:
        req["quantity"] = ext["qty_primary"]
        req["unit_of_measure"] = ext.get("qty_primary_unit") or req.get("unit_of_measure")
        req["_nlp_qty_filled"] = True

    return req


# ══════════════════════════════════════════════════════════════════════════════
# 9.  STANDALONE TEST (validates extraction schema on 5 real requests)
# ══════════════════════════════════════════════════════════════════════════════

def _run_sample_test(requests_path: Path, n: int = 5) -> None:
    """Quick test on n requests — prints extraction results."""
    reqs = json.loads(requests_path.read_text())

    # Pick a representative sample: 1 standard, 1 contradictory, 1 multilingual,
    # 1 missing_info, 1 foreign language
    sample_ids = ["REQ-000001", "REQ-000004", "REQ-000290", "REQ-000002", "REQ-000116"]
    sample = [r for r in reqs if r["request_id"] in sample_ids][:n]

    extractor = NLPExtractor()
    print("\n" + "=" * 64)
    print("NLP EXTRACTOR — SAMPLE TEST")
    print("=" * 64)

    for req in sample:
        print(f"\n--- {req['request_id']} ---")
        print(f"Tags: {req.get('scenario_tags')}")
        print(f"Text: {req['request_text'][:120]}...")
        result = extractor.process(req)
        e = result.extraction

        print(f"  lang detected : {e.detected_language}")
        if e.english_translation:
            print(f"  translation   : {e.english_translation[:100]}...")
        print(f"  qty_primary   : {e.qty_primary} {e.qty_primary_unit}")
        if e.qty_total_rollout:
            print(f"  qty_rollout   : {e.qty_total_rollout}")
        print(f"  budget        : {e.budget_extracted} {e.budget_currency}")
        print(f"  pref_supplier : {e.preferred_supplier_in_text}")
        print(f"  policy_refusal: {e.policy_refusal}")
        print(f"  spec          : {e.spec_mentioned} (higher_cost={e.spec_implies_higher_cost})")
        print(f"  urgency       : {e.urgency_level}")

        if result.contradictions:
            print(f"  CONTRADICTIONS ({len(result.contradictions)}):")
            for c in result.contradictions:
                print(f"    [{c.severity.upper()}] {c.contradiction_type}: {c.description[:80]}")
        else:
            print("  contradictions: none")

        if result.processing_notes:
            print(f"  notes: {result.processing_notes}")

    print("\n" + "=" * 64)


# ══════════════════════════════════════════════════════════════════════════════
# 10.  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    base = Path(__file__).parent
    requests_path = base / "requests.json"

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # Quick 5-request test
        _run_sample_test(requests_path, n=5)
    else:
        # Full batch
        reqs = json.loads(requests_path.read_text())
        extractor = NLPExtractor()
        enriched  = extractor.enrich_batch(reqs, verbose=True)
        out_path  = base / "nlp_results.json"
        out_path.write_text(json.dumps(enriched, indent=2, default=str))
        print(f"\nSaved enriched requests → {out_path}")
