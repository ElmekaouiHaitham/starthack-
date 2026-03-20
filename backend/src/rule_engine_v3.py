"""
rule_engine_v3.py  — ChainIQ START Hack 2026
=============================================
Fully deterministic procurement rule engine.

FIXES vs v2 / original gaps:
  FIX-01  USD threshold fields use different names (min_value vs min_amount)
  FIX-02  10 preferred suppliers with no region_scope silently demoted
  FIX-03  5 category rule types silently dropped (fast_track, design_signoff,
          residency_check, certification_check, performance_baseline)
  FIX-04  MOQ not checked — 384/599 pricing rows have MOQ > 1
  FIX-05  Category rules are conditional (CR-001 >100k, CR-002 >50 units,
          CR-005 >250k, CR-007 >60 days) — must be evaluated at runtime
  FIX-06  Value-conditional restriction (SUP-0045 <75k EUR) never enforced
  FIX-07  57 requests have >1 delivery country — restrictions/geo rules must
          be checked per delivery country, not just request origin
  FIX-08  Region filter for pricing rows not applied — wrong prices selected
  FIX-09  Ranking always runs; escalations are parallel, not a stop gate
  FIX-10  Geography rules GR-005+ have "countries" list, not single "country"
  FIX-11  capacity_per_month is total across all categories — flag > 50%
  FIX-12  Budget currency vs supplier pricing currency conversion (FX rates
          defined as constants; swap for live rates in production)

DESIGN PRINCIPLES:
  • The LLM layer (language detection, field extraction, contradiction NLP)
    is assumed to have already run and produced a clean request dict.
    This engine consumes that dict and applies purely deterministic logic.
  • All escalations are collected; ranking ALWAYS completes.
  • Every decision in the output is linked to a specific rule ID.
  • Status is derived from escalations, not set upfront.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import time

# ══════════════════════════════════════════════════════════════════════════════
# 0.  CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

# FIX-12: Fixed FX rates (EUR base). Replace with live lookup in production.
# All budget/threshold comparisons are done in a canonical currency (EUR).
FX_TO_EUR: dict[str, float] = {
    "EUR": 1.0,
    "CHF": 1.04,   # 1 CHF ≈ 1.04 EUR (Mar 2026 approximate)
    "USD": 0.92,   # 1 USD ≈ 0.92 EUR (Mar 2026 approximate)
}

# FIX-08: Maps ISO country code → pricing region label in merged_v2
COUNTRY_TO_REGION: dict[str, str] = {
    "DE": "EU", "FR": "EU", "NL": "EU", "BE": "EU", "AT": "EU",
    "IT": "EU", "ES": "EU", "PL": "EU", "UK": "EU",
    "CH": "CH",
    "US": "Americas", "CA": "Americas", "BR": "Americas", "MX": "Americas",
    "SG": "APAC",     "AU": "APAC",     "IN": "APAC",     "JP": "APAC",
    "UAE": "MEA",     "ZA": "MEA",
}

# Maps pricing region → canonical threshold currency
REGION_TO_THRESHOLD_CCY: dict[str, str] = {
    "EU": "EUR", "CH": "CHF",
    "Americas": "USD", "APAC": "USD", "MEA": "USD",
}

# Capacity utilisation threshold — flag ER-006 if request > this fraction
CAPACITY_FLAG_FRACTION = 0.50

# How close to a threshold boundary (fraction) triggers a BOUNDARY warning
THRESHOLD_BOUNDARY_FRACTION = 0.05

DATA_DIR = Path(__file__).parent


# ══════════════════════════════════════════════════════════════════════════════
# 1.  NORMALISED POLICY STRUCTURES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ThresholdTier:
    tier_id: str
    currency: str
    min_amount: float
    max_amount: float
    quotes_required: int
    approvers: list[str]
    deviation_approval: list[str]


@dataclass
class PreferredEntry:
    supplier_id: str
    category_l1: str
    category_l2: str
    region_scope: list[str]   # empty = all regions
    policy_note: str


@dataclass
class RestrictionEntry:
    supplier_id: str
    category_l1: str
    category_l2: str
    scope_countries: list[str]   # empty = global
    is_global: bool
    is_value_conditional: bool
    threshold_eur: float | None  # already converted to EUR for comparison
    threshold_raw: float | None
    threshold_ccy: str | None
    reason: str


@dataclass
class CategoryRule:
    rule_id: str
    category_l1: str
    category_l2: str
    rule_type: str
    rule_text: str
    condition_value: float | None     # numeric threshold in the rule text
    condition_currency: str | None
    condition_unit: str | None        # "days", "units", "EUR", etc.


@dataclass
class GeoRule:
    rule_id: str
    countries: list[str]
    rule_type: str
    rule_text: str
    applies_to: list[str]   # category_l1 list; empty = all


# ══════════════════════════════════════════════════════════════════════════════
# 2.  POLICY LOADER
# ══════════════════════════════════════════════════════════════════════════════

def _parse_condition_from_text(text: str) -> tuple[float | None, str | None, str | None]:
    """
    Extract (value, currency, unit) from a rule_text like:
      "...above EUR/CHF 100000"   → (100000, "EUR", None)
      "...above 50 units"          → (50, None, "units")
      "...above 60 consulting days"→ (60, None, "days")
      "...below EUR/CHF 75000"     → (75000, "EUR", None)
    """
    # Currency + number
    m = re.search(r"\b(EUR|CHF|USD)(?:/[A-Z]+)?\s*([\d,]+)", text)
    if m:
        return float(m.group(2).replace(",", "")), m.group(1), None
    # Number + unit
    m = re.search(r"\b([\d,]+)\s+(units?|days?)", text, re.I)
    if m:
        return float(m.group(1).replace(",", "")), None, m.group(2).rstrip("s").lower()
    return None, None, None


def _parse_value_threshold_from_reason(reason: str) -> tuple[float | None, str | None]:
    """Extract first monetary threshold from restriction_reason string."""
    m = re.search(r"(EUR|CHF|USD)\s*([\d,]+)", reason)
    if m:
        return float(m.group(2).replace(",", "")), m.group(1)
    m = re.search(r"below\s+([\d,]+)\s+(EUR|CHF|USD)", reason, re.IGNORECASE)
    if m:
        return float(m.group(1).replace(",", "")), m.group(2).upper()
    return None, None


def load_policies(path: Path) -> dict:
    """
    Parse policies.json into typed, normalised indexes.
    Returns dict with keys: thresholds, preferred, restricted, cat_rules, geo_rules.
    """
    raw = json.loads(path.read_text())

    # ── Thresholds ─────────────────────────────────────────────────────────
    # FIX-01: EUR/CHF use min_amount/max_amount/min_supplier_quotes
    #         USD      uses min_value/max_value/quotes_required
    thresholds: list[ThresholdTier] = []
    for t in raw["approval_thresholds"]:
        thresholds.append(ThresholdTier(
            tier_id=t["threshold_id"],
            currency=t["currency"],
            min_amount=float(t.get("min_amount", t.get("min_value", 0))),
            max_amount=float(t.get("max_amount") or t.get("max_value") or 1e12),
            quotes_required=int(t.get("min_supplier_quotes", t.get("quotes_required", 1))),
            approvers=t.get("managed_by", t.get("approvers", [])),
            deviation_approval=t.get("deviation_approval_required_from", []),
        ))

    # ── Preferred suppliers ────────────────────────────────────────────────
    # FIX-02: missing region_scope → treat as all regions valid
    preferred: list[PreferredEntry] = []
    for p in raw["preferred_suppliers"]:
        preferred.append(PreferredEntry(
            supplier_id=p["supplier_id"],
            category_l1=p["category_l1"],
            category_l2=p["category_l2"],
            region_scope=p.get("region_scope", []),  # empty = no restriction
            policy_note=p.get("policy_note", ""),
        ))

    # ── Restricted suppliers ────────────────────────────────────────────────
    restricted: list[RestrictionEntry] = []
    for r in raw["restricted_suppliers"]:
        scope = r.get("restriction_scope", ["all"])
        reason = r.get("restriction_reason", "")
        threshold_raw, threshold_ccy = _parse_value_threshold_from_reason(reason)
        threshold_eur = None
        if threshold_raw is not None and threshold_ccy:
            threshold_eur = threshold_raw * FX_TO_EUR.get(threshold_ccy, 1.0)
        is_global = (scope == ["all"]) and (threshold_raw is None)
        is_val_cond = threshold_raw is not None
        restricted.append(RestrictionEntry(
            supplier_id=r["supplier_id"],
            category_l1=r["category_l1"],
            category_l2=r["category_l2"],
            scope_countries=[] if scope == ["all"] else scope,
            is_global=is_global,
            is_value_conditional=is_val_cond,
            threshold_eur=threshold_eur,
            threshold_raw=threshold_raw,
            threshold_ccy=threshold_ccy,
            reason=reason,
        ))

    # ── Category rules ──────────────────────────────────────────────────────
    # FIX-03 + FIX-05: parse ALL rule types, extract conditions
    cat_rules: list[CategoryRule] = []
    for c in raw["category_rules"]:
        val, ccy, unit = _parse_condition_from_text(c["rule_text"])
        cat_rules.append(CategoryRule(
            rule_id=c["rule_id"],
            category_l1=c["category_l1"],
            category_l2=c["category_l2"],
            rule_type=c["rule_type"],
            rule_text=c["rule_text"],
            condition_value=val,
            condition_currency=ccy,
            condition_unit=unit,
        ))

    # ── Geography rules ────────────────────────────────────────────────────
    # FIX-10: handle both single "country" key and "countries" list
    geo_rules: list[GeoRule] = []
    for g in raw["geography_rules"]:
        if "countries" in g:
            countries = g["countries"]
        elif "country" in g:
            countries = [g["country"]]
        else:
            countries = []
        geo_rules.append(GeoRule(
            rule_id=g["rule_id"],
            countries=countries,
            rule_type=g.get("rule_type", g.get("rule", "")),
            rule_text=g.get("rule_text", g.get("rule", "")),
            applies_to=g.get("applies_to", []),
        ))

    return {
        "thresholds": thresholds,
        "preferred": preferred,
        "restricted": restricted,
        "cat_rules": cat_rules,
        "geo_rules": geo_rules,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 3.  INDEXES (fast-lookup dicts built from policy lists)
# ══════════════════════════════════════════════════════════════════════════════

def build_indexes(policies: dict) -> dict:
    """
    Pre-build O(1) lookup structures from loaded policy lists.
    """
    # Thresholds: { currency: sorted list of ThresholdTier }
    thresh_by_ccy: dict[str, list[ThresholdTier]] = {}
    for t in policies["thresholds"]:
        thresh_by_ccy.setdefault(t.currency, []).append(t)
    for ccy in thresh_by_ccy:
        thresh_by_ccy[ccy].sort(key=lambda x: x.min_amount)

    # Preferred: { (supplier_id, cat_l1, cat_l2): PreferredEntry }
    pref_idx: dict[tuple, PreferredEntry] = {}
    for p in policies["preferred"]:
        pref_idx[(p.supplier_id, p.category_l1, p.category_l2)] = p

    # Restricted: { (supplier_id, cat_l1, cat_l2): list[RestrictionEntry] }
    rest_idx: dict[tuple, list[RestrictionEntry]] = {}
    for r in policies["restricted"]:
        key = (r.supplier_id, r.category_l1, r.category_l2)
        rest_idx.setdefault(key, []).append(r)

    # Category rules: { (cat_l1, cat_l2): list[CategoryRule] }
    cat_idx: dict[tuple, list[CategoryRule]] = {}
    for c in policies["cat_rules"]:
        cat_idx.setdefault((c.category_l1, c.category_l2), []).append(c)

    # Geography rules: { country: list[GeoRule] }
    geo_idx: dict[str, list[GeoRule]] = {}
    for g in policies["geo_rules"]:
        for country in g.countries:
            geo_idx.setdefault(country, []).append(g)

    return {
        "thresh_by_ccy": thresh_by_ccy,
        "pref_idx": pref_idx,
        "rest_idx": rest_idx,
        "cat_idx": cat_idx,
        "geo_idx": geo_idx,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 4.  CURRENCY UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def to_eur(amount: float, from_ccy: str) -> float:
    """Convert any supported currency to EUR for comparison."""
    return amount * FX_TO_EUR.get(from_ccy, 1.0)


def convert(amount: float, from_ccy: str, to_ccy: str) -> float:
    """Convert between any two supported currencies via EUR."""
    if from_ccy == to_ccy:
        return amount
    eur = to_eur(amount, from_ccy)
    return eur / FX_TO_EUR.get(to_ccy, 1.0)


# ══════════════════════════════════════════════════════════════════════════════
# 5.  THRESHOLD EVALUATION
# ══════════════════════════════════════════════════════════════════════════════

def get_threshold_tier(
    contract_value: float,
    request_currency: str,
    delivery_region: str,
    thresh_by_ccy: dict[str, list[ThresholdTier]],
) -> tuple[ThresholdTier | None, str]:
    """
    Find the applicable approval threshold tier.

    The tier currency is determined by the delivery region, NOT the request
    budget currency. If the request budget is in a different currency than
    the threshold table, convert the contract value.

    Returns (tier, notes_string).
    """
    threshold_ccy = REGION_TO_THRESHOLD_CCY.get(delivery_region, "EUR")
    tiers = thresh_by_ccy.get(threshold_ccy, [])
    if not tiers:
        return None, f"No threshold table for currency {threshold_ccy}"

    # FIX-12: Convert contract value to threshold currency if needed
    if request_currency != threshold_ccy:
        converted = convert(contract_value, request_currency, threshold_ccy)
        notes = (
            f"Contract value {request_currency} {contract_value:,.2f} converted to "
            f"{threshold_ccy} {converted:,.2f} (rate: {FX_TO_EUR[request_currency]/FX_TO_EUR[threshold_ccy]:.4f}) "
            f"for threshold comparison."
        )
    else:
        converted = contract_value
        notes = ""

    matched_tier = None
    for t in tiers:
        if t.min_amount <= converted <= t.max_amount:
            matched_tier = t
            break
    if matched_tier is None and tiers:
        # Above all defined tiers — take the highest
        matched_tier = tiers[-1]

    # FIX boundary warning
    boundary_notes = ""
    if matched_tier:
        distance_to_next = None
        for t in tiers:
            if t.min_amount > matched_tier.min_amount:
                distance_to_next = t.min_amount - converted
                if distance_to_next / max(matched_tier.max_amount, 1) < THRESHOLD_BOUNDARY_FRACTION:
                    pct = abs(distance_to_next) / t.min_amount * 100
                    boundary_notes = (
                        f"BOUNDARY WARNING: value is {pct:.1f}% below the "
                        f"{threshold_ccy} {t.min_amount:,.0f} boundary for "
                        f"{t.tier_id}. Conservative tier applied."
                    )
                break

    return matched_tier, " ".join(filter(None, [notes, boundary_notes]))


# ══════════════════════════════════════════════════════════════════════════════
# 6.  SUPPLIER ELIGIBILITY
# ══════════════════════════════════════════════════════════════════════════════

def _supplier_covers_all_countries(service_regions_str: str, countries: list[str]) -> bool:
    """
    Returns True iff every country in `countries` appears in the
    semicolon-delimited service_regions string.
    FIX-07: exact token match, not substring.
    """
    covered = set(service_regions_str.split(";"))
    return all(c in covered for c in countries)


def _check_restrictions(
    supplier_id: str,
    category_l1: str,
    category_l2: str,
    delivery_countries: list[str],
    contract_value_eur: float,
    rest_idx: dict,
) -> list[dict]:
    """
    Two-pass restriction check.
    FIX-06 + FIX-07: evaluate country-scoped AND value-conditional restrictions
    per each delivery country.

    Returns list of violation dicts (empty = supplier is eligible).
    """
    violations = []
    entries = rest_idx.get((supplier_id, category_l1, category_l2), [])

    for entry in entries:
        # Global unconditional ban
        if entry.is_global:
            violations.append({
                "type": "global_restriction",
                "rule": "ER-002",
                "reason": entry.reason,
            })
            continue

        # Country-scoped restriction — FIX-07: check per delivery country
        if entry.scope_countries:
            hit_countries = [c for c in delivery_countries if c in entry.scope_countries]
            if hit_countries:
                if not entry.is_value_conditional:
                    violations.append({
                        "type": "country_restriction",
                        "countries": hit_countries,
                        "rule": "ER-002",
                        "reason": entry.reason,
                    })
                else:
                    # FIX-06: value-conditional + country-scoped
                    if entry.threshold_eur is not None and contract_value_eur >= entry.threshold_eur:
                        violations.append({
                            "type": "value_conditional_country_restriction",
                            "countries": hit_countries,
                            "rule": "ER-002",
                            "contract_value_eur": contract_value_eur,
                            "threshold_eur": entry.threshold_eur,
                            "reason": entry.reason,
                        })
        else:
            # Scope is "all" countries but value-conditional
            if entry.is_value_conditional:
                if entry.threshold_eur is not None and contract_value_eur >= entry.threshold_eur:
                    violations.append({
                        "type": "value_conditional_global_restriction",
                        "rule": "ER-002",
                        "contract_value_eur": contract_value_eur,
                        "threshold_eur": entry.threshold_eur,
                        "reason": entry.reason,
                    })

    return violations


def _is_preferred(
    supplier_id: str,
    category_l1: str,
    category_l2: str,
    delivery_region: str,
    pref_idx: dict,
) -> bool:
    """
    FIX-02: missing region_scope = preferred in all regions.
    """
    entry = pref_idx.get((supplier_id, category_l1, category_l2))
    if entry is None:
        return False
    if not entry.region_scope:   # empty = no regional restriction
        return True
    return delivery_region in entry.region_scope


# ══════════════════════════════════════════════════════════════════════════════
# 7.  PRICING TIER SELECTION
# ══════════════════════════════════════════════════════════════════════════════

def select_pricing_tier(
    merged: pd.DataFrame,
    supplier_id: str,
    category_l1: str,
    category_l2: str,
    delivery_region: str,
    quantity: float,
    use_expedited: bool,
) -> dict | None:
    """
    FIX-04 + FIX-08: Filter by region AND check MOQ before tier selection.
    Returns the best matching pricing row as a dict, or None.
    """
    rows = merged[
        (merged["supplier_id"] == supplier_id)
        & (merged["category_l1"] == category_l1)
        & (merged["category_l2"] == category_l2)
        & (merged["region"] == delivery_region)
        & (merged["min_quantity"] <= quantity)
        & (merged["max_quantity"] >= quantity)
        & (merged["moq"] <= quantity)    # FIX-04: MOQ check
    ]

    if rows.empty:
        # Check if supplier exists in this category/region at all
        exists = merged[
            (merged["supplier_id"] == supplier_id)
            & (merged["category_l2"] == category_l2)
            & (merged["region"] == delivery_region)
        ]
        return None

    row = rows.iloc[0].to_dict()
    unit_price = row["expedited_unit_price"] if use_expedited else row["unit_price"]
    lead_time = row["expedited_lead_time"] if use_expedited else row["standard_lead_time"]

    return {
        "supplier_id": row["supplier_id"],
        "supplier_name": row["supplier_name"],
        "region": row["region"],
        "currency": row["currency"],
        "pricing_model": row["pricing_model"],
        "tier_min_qty": row["min_quantity"],
        "tier_max_qty": row["max_quantity"],
        "moq": row["moq"],
        "unit_price": unit_price,
        "unit_price_standard": row["unit_price"],
        "unit_price_expedited": row["expedited_unit_price"],
        "lead_time_days": lead_time,
        "standard_lead_time_days": row["standard_lead_time"],
        "expedited_lead_time_days": row["expedited_lead_time"],
        "quality_score": row["quality_score"],
        "risk_score": row["risk_score"],
        "esg_score": row["esg_score"],
        "capacity_per_month": row["capacity_per_month"],
        "data_residency_supported": row["data_residency_supported"],
        "is_preferred": row["is_preferred"],
        "is_restricted_global": row["is_restricted_global"],
        "is_restricted_countries": row["is_restricted_countries"],
        "is_restricted_value_conditional": row["is_restricted_value_conditional"],
        "restriction_value_threshold": row["restriction_value_threshold"],
        "service_regions": row["service_regions"],
        "requires_security_review": row["requires_security_review"],
        "requires_cv_review": row["requires_cv_review"],
        "requires_brand_safety": row["requires_brand_safety"],
        "requires_engineering_so": row["requires_engineering_so"],
        "requires_mandatory_comparison": row["requires_mandatory_comparison"],
        "expedited_used": use_expedited,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 8.  CATEGORY RULE EVALUATION
# ══════════════════════════════════════════════════════════════════════════════

def evaluate_category_rules(
    category_l1: str,
    category_l2: str,
    quantity: float,
    contract_value_eur: float,
    unit_of_measure: str,
    cat_idx: dict,
) -> list[dict]:
    """
    FIX-03 + FIX-05: Evaluate ALL category rules with conditional thresholds.
    Handles both "above X" (standard) and "below X" (relaxing fast_track) conditions.
    Returns list of applicable rule dicts.
    """
    applicable = []
    rules = cat_idx.get((category_l1, category_l2), [])

    for rule in rules:
        triggered = False
        context = ""

        if rule.condition_value is not None:
            threshold_eur = rule.condition_value * FX_TO_EUR.get(
                rule.condition_currency or "EUR", 1.0
            )
            # Determine direction from rule_text: fast_track fires BELOW threshold
            # All other rules fire ABOVE threshold
            is_below_rule = rule.rule_type == "fast_track" or (
                "below" in rule.rule_text.lower()
            )

            if rule.condition_currency:
                # Value-based condition
                if is_below_rule:
                    if contract_value_eur < threshold_eur:
                        triggered = True
                        context = (
                            f"contract value EUR {contract_value_eur:,.0f} < "
                            f"{rule.condition_currency} {rule.condition_value:,.0f} threshold "
                            f"(fast-track eligible)"
                        )
                else:
                    if contract_value_eur >= threshold_eur:
                        triggered = True
                        context = (
                            f"contract value EUR {contract_value_eur:,.0f} ≥ "
                            f"{rule.condition_currency} {rule.condition_value:,.0f} threshold"
                        )
            elif rule.condition_unit:
                # Quantity/day-based condition
                if quantity >= rule.condition_value:
                    triggered = True
                    context = (
                        f"quantity {quantity} {unit_of_measure} ≥ "
                        f"{rule.condition_value} {rule.condition_unit} threshold"
                    )
        else:
            # Unconditional rules (brand_safety, design_signoff, etc.)
            triggered = True
            context = "unconditional for this category"

        if triggered:
            applicable.append({
                "rule_id": rule.rule_id,
                "rule_type": rule.rule_type,
                "rule_text": rule.rule_text,
                "context": context,
                "is_relaxing": rule.rule_type == "fast_track",
            })

    return applicable


# ══════════════════════════════════════════════════════════════════════════════
# 9.  GEOGRAPHY RULE EVALUATION
# ══════════════════════════════════════════════════════════════════════════════

def evaluate_geo_rules(
    delivery_countries: list[str],
    category_l1: str,
    data_residency_constraint: bool,
    geo_idx: dict,
) -> list[dict]:
    """
    FIX-10: Evaluate per delivery country; handle both "country" and "countries"
    key structures in policies.json.
    """
    applicable = []
    seen = set()
    for country in delivery_countries:
        for rule in geo_idx.get(country, []):
            if rule.rule_id in seen:
                continue
            # applies_to filter (empty = all categories)
            if rule.applies_to and category_l1 not in rule.applies_to:
                continue
            seen.add(rule.rule_id)
            applicable.append({
                "rule_id": rule.rule_id,
                "rule_type": rule.rule_type,
                "applies_to_countries": [c for c in delivery_countries if c in rule.countries],
                "rule_text": rule.rule_text,
            })

    # ER-005: data residency constraint — flag if no compliant supplier can be found
    # (actual supplier check is done in the supplier loop; here we just note the requirement)
    if data_residency_constraint:
        applicable.append({
            "rule_id": "DR-REQ",
            "rule_type": "data_residency_required",
            "applies_to_countries": delivery_countries,
            "rule_text": "data_residency_constraint=True — only suppliers with data_residency_supported=True are eligible.",
        })

    return applicable


# ══════════════════════════════════════════════════════════════════════════════
# 10.  SUPPLIER RANKING
# ══════════════════════════════════════════════════════════════════════════════

def score_supplier(
    pricing_row: dict,
    contract_value: float,
    budget_amount: float | None,
    request_currency: str,
    is_preferred: bool,
    is_incumbent: bool,
    esg_required: bool,
    weights: dict | None = None,
) -> float:
    """
    Multi-criteria score. Higher = better.
    FIX-12: budget comparison is currency-aware.

    Weights (0–1, sum to 1.0 approximately):
      price_competitiveness : 0.30
      quality               : 0.25
      risk (inverted)       : 0.20
      esg                   : 0.10  (0.20 if esg_required)
      preferred_bonus       : 0.10
      incumbent_bonus       : 0.05
    """
    w = weights or {
        "price": 0.30,
        "quality": 0.25,
        "risk": 0.20,
        "esg": 0.10 if not esg_required else 0.20,
        "preferred": 0.10,
        "incumbent": 0.05,
    }

    # Price competitiveness: savings vs budget (capped 0–1)
    price_score = 0.5  # neutral if no budget
    if budget_amount and budget_amount > 0:
        # FIX-12: convert pricing to request currency for fair comparison
        contract_in_req_ccy = convert(contract_value, pricing_row["currency"], request_currency)
        savings_pct = (budget_amount - contract_in_req_ccy) / budget_amount
        price_score = max(0.0, min(1.0, 0.5 + savings_pct))  # centre at 0 savings

    quality_score = pricing_row["quality_score"] / 100.0
    risk_score    = 1.0 - (pricing_row["risk_score"] / 100.0)    # lower risk = better
    esg_score     = pricing_row["esg_score"] / 100.0
    pref_score    = 1.0 if is_preferred else 0.0
    inc_score     = 1.0 if is_incumbent else 0.0

    total = (
        w["price"]     * price_score
        + w["quality"] * quality_score
        + w["risk"]    * risk_score
        + w["esg"]     * esg_score
        + w["preferred"] * pref_score
        + w["incumbent"] * inc_score
    )

    return round(total, 4)


# ══════════════════════════════════════════════════════════════════════════════
# 11.  MAIN ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class ProcurementRuleEngine:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self._load()

    def _load(self):
        self.merged   = pd.read_csv(self.data_dir / "../data/merged_v2.csv")
        self.policies = load_policies(self.data_dir / "../data/policies.json")
        self.indexes  = build_indexes(self.policies)
        self.awards   = pd.read_csv(self.data_dir / "../data/historical_awards.csv")
        print(f"Loaded {len(self.merged)} pricing rows, "
              f"{len(self.awards)} historical awards.")

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC: process one request
    # ─────────────────────────────────────────────────────────────────────────

    def process(self, request: dict) -> dict:
        """
        Full deterministic evaluation of a single purchase request.
        All escalations run IN PARALLEL with ranking — FIX-09.
        """
        now = datetime.utcnow().isoformat() + "Z"
        escalations: list[dict] = []
        policies_checked: list[str] = []

        # ── Step 1: basic fields ────────────────────────────────────────────
        req_id          = request.get("request_id", f"req_{int(time.time())}")
        category_l1     = request.get("category_l1", "")
        category_l2     = request.get("category_l2", "")
        quantity        = request.get("quantity")         # may be None
        unit_of_measure = request.get("unit_of_measure", "unit")
        budget_amount   = request.get("budget_amount")    # may be None
        req_currency    = request.get("currency", "EUR")
        origin_country  = request.get("country", "")
        delivery_countries = request.get("delivery_countries", [origin_country])
        data_residency  = bool(request.get("data_residency_constraint", False))
        esg_required    = bool(request.get("esg_requirement", False))
        preferred_named = request.get("preferred_supplier_mentioned")
        incumbent_named = request.get("incumbent_supplier")
        required_by_str = request.get("required_by_date")
        created_at_str  = request.get("created_at", now)

        # ── Step 2: derived values ──────────────────────────────────────────
        # FIX-08: determine delivery region from origin country
        delivery_region = COUNTRY_TO_REGION.get(origin_country, "EU")

        # Days until required
        days_until_required = None
        if required_by_str:
            try:
                req_date     = date.fromisoformat(required_by_str)
                created_date = datetime.fromisoformat(
                    created_at_str.replace("Z", "+00:00")
                ).date()
                days_until_required = (req_date - created_date).days
            except Exception:
                pass

        # Estimate contract value (may be unknown if quantity/budget null)
        contract_value_est: float | None = None
        if budget_amount is not None:
            contract_value_est = budget_amount

        contract_value_eur: float = (
            to_eur(contract_value_est, req_currency)
            if contract_value_est else 0.0
        )

        # ── Step 2b: consume NLP enrichment if present ──────────────────────
        # The NLP extractor (nlp_extractor.py) enriches requests with:
        #   _nlp_contradictions : list of detected text vs field conflicts
        #   _nlp_policy_refusal : policy bypass attempt in text
        #   _nlp_qty_override   : corrected quantity from text
        #   _nlp_translation    : English translation if request was non-English
        # Rule engine reads these and incorporates them into its output.
        nlp_contradictions = request.get("_nlp_contradictions", [])
        nlp_policy_refusal = request.get("_nlp_policy_refusal")
        nlp_qty_override   = request.get("_nlp_qty_override")
        nlp_translation    = request.get("_nlp_translation")
        working_text       = request.get("_working_text", request.get("request_text", ""))

        # If NLP found a better quantity and the original is null, use it
        if quantity is None and nlp_qty_override:
            quantity = nlp_qty_override.get("qty_from_text")
            unit_of_measure = nlp_qty_override.get("unit") or unit_of_measure

        # ── Step 3: completeness check (ER-001) ─────────────────────────────
        missing_fields = []
        if budget_amount is None:
            missing_fields.append("budget_amount")
        if quantity is None:
            missing_fields.append("quantity")
        if not category_l2:
            missing_fields.append("category_l2")

        if missing_fields:
            escalations.append({
                "escalation_id": f"ESC-{len(escalations)+1:03d}",
                "rule": "ER-001",
                "trigger": f"Missing required fields: {', '.join(missing_fields)}",
                "escalate_to": "Requester Clarification",
                "blocking": True,
                "missing_fields": missing_fields,
            })
            policies_checked.append("ER-001")

        # Surface NLP-detected contradictions as additional ER-001 issues
        critical_contra = [c for c in nlp_contradictions
                           if c.get("severity") == "critical"]
        if critical_contra:
            for contra in critical_contra:
                escalations.append({
                    "escalation_id": f"ESC-{len(escalations)+1:03d}",
                    "rule": "ER-001",
                    "trigger": (
                        f"[NLP] {contra['contradiction_type']}: {contra['description']}"
                    ),
                    "escalate_to": "Requester Clarification",
                    "blocking": True,
                    "recommended_action": contra.get("recommended_action"),
                    "source": "nlp_contradiction",
                })
            policies_checked.append("ER-001")

        # Policy refusal from NLP (e.g. "no exception" mandate)
        if nlp_policy_refusal:
            refusal_type = nlp_policy_refusal.get("refusal_type", "")
            if refusal_type in ("no_exception_mandate", "skip_competitive_tender"):
                escalations.append({
                    "escalation_id": f"ESC-{len(escalations)+1:03d}",
                    "rule": "ER-002",
                    "trigger": (
                        f"[NLP] Requester instruction conflicts with procurement policy: "
                        f"'{nlp_policy_refusal.get('phrase')}'. "
                        f"Applies to: {nlp_policy_refusal.get('applies_to')}."
                    ),
                    "escalate_to": "Procurement Manager",
                    "blocking": False,
                    "source": "nlp_policy_refusal",
                })

        # ── Step 4: preferred supplier validation ────────────────────────────
        preferred_supplier_status = None
        if preferred_named:
            preferred_supplier_status = self._check_preferred_supplier(
                preferred_named, category_l1, category_l2,
                delivery_countries, delivery_region,
                contract_value_eur, escalations, policies_checked
            )

        # ── Step 5: category rules (conditional, FIX-03+FIX-05) ─────────────
        applicable_cat_rules = evaluate_category_rules(
            category_l1, category_l2,
            quantity or 0, contract_value_eur, unit_of_measure,
            self.indexes["cat_idx"],
        )
        for r in applicable_cat_rules:
            policies_checked.append(r["rule_id"])

        # fast_track: may relax quote requirement
        fast_track_active = any(r["is_relaxing"] for r in applicable_cat_rules)

        # ── Step 6: geography rules (FIX-10) ────────────────────────────────
        applicable_geo_rules = evaluate_geo_rules(
            delivery_countries, category_l1, data_residency,
            self.indexes["geo_idx"],
        )
        for r in applicable_geo_rules:
            policies_checked.append(r.get("rule_id", ""))

        # ── Step 7: build candidate supplier list ────────────────────────────
        # Filter merged to this category + delivery region
        # If quantity is None, we can still rank — use 1 as placeholder
        qty_for_filter = quantity if quantity else 1

        # Determine if expedited is needed
        use_expedited = False
        if days_until_required is not None and days_until_required >= 0:
            # Check cheapest supplier's standard lead time; if any exceed deadline, try expedited
            candidate_rows = self.merged[
                (self.merged["category_l1"] == category_l1)
                & (self.merged["category_l2"] == category_l2)
                & (self.merged["region"] == delivery_region)
            ]
            if not candidate_rows.empty:
                min_std_lt = candidate_rows["standard_lead_time"].min()
                if min_std_lt > days_until_required:
                    use_expedited = True

        # Collect all unique suppliers for this category/region
        candidate_ids = self.merged[
            (self.merged["category_l1"] == category_l1)
            & (self.merged["category_l2"] == category_l2)
            & (self.merged["region"] == delivery_region)
        ]["supplier_id"].unique()

        shortlist: list[dict] = []
        excluded: list[dict] = []

        for sup_id in candidate_ids:
            # Select pricing tier for this supplier (FIX-04 + FIX-08)
            pricing = select_pricing_tier(
                self.merged, sup_id, category_l1, category_l2,
                delivery_region, qty_for_filter, use_expedited
            )
            if pricing is None:
                excluded.append({
                    "supplier_id": sup_id,
                    "reason": (
                        f"No valid pricing tier for qty={qty_for_filter} "
                        f"in region={delivery_region} (MOQ or tier mismatch)"
                    ),
                })
                continue

            sup_name = pricing["supplier_name"]

            # Geography coverage check (FIX-07: ALL delivery countries)
            if not _supplier_covers_all_countries(
                pricing["service_regions"], delivery_countries
            ):
                missing = [
                    c for c in delivery_countries
                    if c not in pricing["service_regions"].split(";")
                ]
                excluded.append({
                    "supplier_id": sup_id,
                    "supplier_name": sup_name,
                    "reason": f"Does not serve delivery countries: {missing}",
                })
                continue

            # Data residency check (ER-005)
            if data_residency and not pricing["data_residency_supported"]:
                excluded.append({
                    "supplier_id": sup_id,
                    "supplier_name": sup_name,
                    "reason": "data_residency_constraint=True but supplier lacks local data hosting (ER-005)",
                })
                continue

            # Compute contract value in supplier pricing currency
            total_in_sup_ccy = pricing["unit_price"] * qty_for_filter

            # FIX-12: Convert to EUR for restriction threshold comparison
            total_eur = to_eur(total_in_sup_ccy, pricing["currency"])

            # Restriction check — two pass (FIX-06 + FIX-07)
            violations = _check_restrictions(
                sup_id, category_l1, category_l2,
                delivery_countries, total_eur,
                self.indexes["rest_idx"],
            )
            if violations:
                is_preferred_sup = _is_preferred(
                    sup_id, category_l1, category_l2,
                    delivery_region, self.indexes["pref_idx"]
                )
                # If this is the named preferred supplier → ER-002 escalation
                if preferred_named and sup_name == preferred_named:
                    if not any(e["rule"] == "ER-002" for e in escalations):
                        escalations.append({
                            "escalation_id": f"ESC-{len(escalations)+1:03d}",
                            "rule": "ER-002",
                            "trigger": (
                                f"Preferred supplier '{preferred_named}' is restricted: "
                                + "; ".join(v["reason"] for v in violations)
                            ),
                            "escalate_to": "Procurement Manager",
                            "blocking": False,
                            "violations": violations,
                        })
                        policies_checked.append("ER-002")
                excluded.append({
                    "supplier_id": sup_id,
                    "supplier_name": sup_name,
                    "reason": "Restriction: " + "; ".join(v["type"] for v in violations),
                    "violation_detail": violations,
                })
                continue

            # FIX-11: Capacity check (conservative — flag if > 50% of monthly cap)
            cap = pricing["capacity_per_month"]
            capacity_flag = False
            if qty_for_filter > cap:
                escalations.append({
                    "escalation_id": f"ESC-{len(escalations)+1:03d}",
                    "rule": "ER-006",
                    "trigger": (
                        f"Requested qty {qty_for_filter} exceeds {sup_name} "
                        f"monthly capacity {cap}. Partial or split fulfillment required."
                    ),
                    "escalate_to": "Sourcing Excellence Lead",
                    "blocking": False,
                    "supplier_id": sup_id,
                })
                policies_checked.append("ER-006")
                capacity_flag = True
            elif qty_for_filter > cap * CAPACITY_FLAG_FRACTION:
                capacity_flag = True  # soft warning, not an escalation

            # Lead time check
            lead_time_feasible = True
            lead_time_note = ""
            if days_until_required is not None:
                if pricing["lead_time_days"] > days_until_required:
                    lead_time_feasible = False
                    lead_time_note = (
                        f"{'Expedited' if use_expedited else 'Standard'} lead time "
                        f"{pricing['lead_time_days']}d exceeds {days_until_required}d available."
                    )

            # Budget sufficiency check (FIX-12: currency-aware)
            budget_sufficient = True
            budget_note = ""
            if budget_amount is not None:
                # Convert supplier price to request currency
                total_in_req_ccy = convert(total_in_sup_ccy, pricing["currency"], req_currency)
                if total_in_req_ccy > budget_amount:
                    budget_sufficient = False
                    shortfall = total_in_req_ccy - budget_amount
                    budget_note = (
                        f"Total {pricing['currency']} {total_in_sup_ccy:,.2f} "
                        f"(≈ {req_currency} {total_in_req_ccy:,.2f}) "
                        f"exceeds budget {req_currency} {budget_amount:,.2f} "
                        f"by {req_currency} {shortfall:,.2f}."
                    )
                    if req_currency != pricing["currency"]:
                        budget_note += (
                            f" [FX: 1 {pricing['currency']} = "
                            f"{convert(1, pricing['currency'], req_currency):.4f} {req_currency}]"
                        )

            # Preferred status (FIX-02: respect missing region_scope)
            is_pref = _is_preferred(
                sup_id, category_l1, category_l2,
                delivery_region, self.indexes["pref_idx"]
            )
            is_incumbent = bool(incumbent_named and incumbent_named == sup_name)

            # Score (ALWAYS, even if infeasible — FIX-09)
            score = score_supplier(
                pricing, total_in_sup_ccy, budget_amount,
                req_currency, is_pref, is_incumbent, esg_required
            )

            shortlist.append({
                "supplier_id": sup_id,
                "supplier_name": sup_name,
                "preferred": is_pref,
                "incumbent": is_incumbent,
                # Canonical names (internal)
                "pricing_tier": f"{int(pricing['tier_min_qty'])}–{int(pricing['tier_max_qty'])}",
                # Schema-compliant alias (matches example_output.json)
                "pricing_tier_applied": f"{int(pricing['tier_min_qty'])}–{int(pricing['tier_max_qty'])} units",
                "moq": pricing["moq"],
                "unit_price": pricing["unit_price"],
                "unit_price_standard": pricing["unit_price_standard"],
                "unit_price_expedited": pricing["unit_price_expedited"],
                "pricing_currency": pricing["currency"],
                "total_price": total_in_sup_ccy,
                "total_price_in_req_currency": round(
                    convert(total_in_sup_ccy, pricing["currency"], req_currency), 2
                ),
                "req_currency": req_currency,
                "fx_applied": pricing["currency"] != req_currency,
                "fx_rate": (
                    round(convert(1, pricing["currency"], req_currency), 4)
                    if pricing["currency"] != req_currency else None
                ),
                "expedited_used": use_expedited,
                "standard_lead_time_days": pricing["standard_lead_time_days"],
                "expedited_lead_time_days": pricing["expedited_lead_time_days"],
                "lead_time_days": pricing["lead_time_days"],
                "lead_time_feasible": lead_time_feasible,
                "lead_time_note": lead_time_note,
                "budget_sufficient": budget_sufficient,
                "budget_note": budget_note,
                "quality_score": pricing["quality_score"],
                "risk_score": pricing["risk_score"],
                "esg_score": pricing["esg_score"],
                "capacity_per_month": cap,
                "capacity_flag": capacity_flag,
                "data_residency_supported": pricing["data_residency_supported"],
                "covers_delivery_country": True,   # passed geo check above
                "policy_compliant": True,
                "score": score,
                "recommendation_note": "",  # filled by rationale_generator
            })

        # ── Step 8: sort shortlist (FIX-09: ALWAYS rank) ────────────────────
        shortlist.sort(key=lambda x: x["score"], reverse=True)
        for i, s in enumerate(shortlist):
            s["rank"] = i + 1

        # ── Step 9: approval threshold ───────────────────────────────────────
        # Use best-price supplier's total as the estimated contract value
        best_total_in_req_ccy = None
        if shortlist and quantity:
            best_total_in_req_ccy = shortlist[0]["total_price_in_req_currency"]

        effective_contract_value = best_total_in_req_ccy or contract_value_est or 0.0
        tier, threshold_notes = get_threshold_tier(
            effective_contract_value, req_currency, delivery_region,
            self.indexes["thresh_by_ccy"],
        )
        policies_checked.append(tier.tier_id if tier else "unknown_tier")

        # ER-003: high-value escalation (Tier 4+)
        if tier and tier.deviation_approval and any(
            "Strategic Sourcing" in a or "CPO" in a
            for a in tier.deviation_approval
        ):
            escalations.append({
                "escalation_id": f"ESC-{len(escalations)+1:03d}",
                "rule": "ER-003",
                "trigger": (
                    f"Contract value {req_currency} {effective_contract_value:,.2f} "
                    f"falls in {tier.tier_id} requiring {tier.deviation_approval} approval."
                ),
                "escalate_to": tier.deviation_approval[0],
                "blocking": False,
            })
            policies_checked.append("ER-003")

        # ── Step 10: quote sufficiency check ────────────────────────────────
        required_quotes = 1 if fast_track_active else (tier.quotes_required if tier else 1)
        if len(shortlist) < required_quotes:
            if len(shortlist) == 0:
                escalations.append({
                    "escalation_id": f"ESC-{len(escalations)+1:03d}",
                    "rule": "ER-004",
                    "trigger": (
                        f"No compliant supplier found for {category_l2} in {delivery_region}. "
                        f"Excluded suppliers: {[e['supplier_id'] for e in excluded]}"
                    ),
                    "escalate_to": "Head of Category",
                    "blocking": True,
                    "excluded_count": len(excluded),
                })
                policies_checked.append("ER-004")
            else:
                escalations.append({
                    "escalation_id": f"ESC-{len(escalations)+1:03d}",
                    "rule": "ER-004",
                    "trigger": (
                        f"Only {len(shortlist)} compliant supplier(s) found; "
                        f"{required_quotes} quotes required by {tier.tier_id if tier else 'policy'}."
                    ),
                    "escalate_to": "Head of Category",
                    "blocking": False,
                })
                policies_checked.append("ER-004")

        # ── Step 11: data residency escalation (ER-005) ──────────────────────
        if data_residency:
            residency_ok = any(s["data_residency_supported"] for s in shortlist)
            if not residency_ok:
                escalations.append({
                    "escalation_id": f"ESC-{len(escalations)+1:03d}",
                    "rule": "ER-005",
                    "trigger": (
                        "data_residency_constraint=True but no compliant supplier "
                        "supports local data residency in the delivery region."
                    ),
                    "escalate_to": "Security and Compliance Review",
                    "blocking": True,
                })
                policies_checked.append("ER-005")

        # ── Step 12: lead time infeasibility (ER-004 sub-case) ───────────────
        if days_until_required is not None and days_until_required >= 0 and shortlist:
            all_infeasible = all(not s["lead_time_feasible"] for s in shortlist)
            if all_infeasible:
                if not any(e.get("rule") == "lead_time_infeasible" for e in escalations):
                    escalations.append({
                        "escalation_id": f"ESC-{len(escalations)+1:03d}",
                        "rule": "ER-004",
                        "trigger": (
                            f"Required delivery in {days_until_required} days. "
                            f"All {'expedited' if use_expedited else 'standard'} lead times exceed this. "
                            f"Shortest available: {min(s['lead_time_days'] for s in shortlist)} days."
                        ),
                        "escalate_to": "Head of Category",
                        "blocking": True,
                        "sub_type": "lead_time_infeasible",
                    })

        # ── Step 13: brand safety (ER-007) ──────────────────────────────────
        brand_safety_rules = [r for r in applicable_cat_rules if r["rule_type"] == "brand_safety"]
        if brand_safety_rules:
            escalations.append({
                "escalation_id": f"ESC-{len(escalations)+1:03d}",
                "rule": "ER-007",
                "trigger": f"Category {category_l2} requires brand-safety review before award.",
                "escalate_to": "Marketing Governance Lead",
                "blocking": False,
            })
            policies_checked.append("ER-007")

        # ── Step 14: threshold boundary escalation ────────────────────────────
        if "BOUNDARY WARNING" in threshold_notes:
            escalations.append({
                "escalation_id": f"ESC-{len(escalations)+1:03d}",
                "rule": "AT-BOUNDARY",
                "trigger": threshold_notes,
                "escalate_to": "Procurement Manager",
                "blocking": False,
                "note": "Conservative tier applied. Verify final contract value before award.",
            })

        # ── Step 15: budget insufficient → ER-001 ────────────────────────────
        if budget_amount is not None and shortlist:
            all_over_budget = all(not s["budget_sufficient"] for s in shortlist)
            if all_over_budget:
                min_total = min(s["total_price_in_req_currency"] for s in shortlist)
                if not any(e.get("sub_type") == "budget_insufficient" for e in escalations):
                    escalations.append({
                        "escalation_id": f"ESC-{len(escalations)+1:03d}",
                        "rule": "ER-001",
                        "trigger": (
                            f"Budget {req_currency} {budget_amount:,.2f} is insufficient. "
                            f"Minimum feasible total: {req_currency} {min_total:,.2f}. "
                            f"Shortfall: {req_currency} {min_total - budget_amount:,.2f}."
                        ),
                        "escalate_to": "Requester Clarification",
                        "blocking": True,
                        "sub_type": "budget_insufficient",
                        "minimum_budget_required": round(min_total, 2),
                        "currency": req_currency,
                    })

        # ── Step 16: historical context ──────────────────────────────────────
        historical_note = self._get_historical_context(req_id, category_l2, origin_country)

        # ── Step 17: determine overall status (FIX-09) ──────────────────────
        has_blocking = any(e.get("blocking", False) for e in escalations)
        if has_blocking:
            status = "cannot_proceed"
        elif escalations:
            status = "proceed_with_conditions"
        else:
            status = "proceed"

        # ── Assemble output ──────────────────────────────────────────────────
        nlp_filled = request.get("_nlp_filled_fields", {})

        # Build validation.issues_detected (structured problem list)
        issues_detected = []
        _issue_id = [0]
        def add_issue(severity, itype, desc, action):
            _issue_id[0] += 1
            issues_detected.append({
                "issue_id": f"V-{_issue_id[0]:03d}",
                "severity": severity,
                "type": itype,
                "description": desc,
                "action_required": action,
            })

        # Budget insufficient?
        if budget_amount is not None and shortlist:
            min_total = min(s["total_price_in_req_currency"] for s in shortlist)
            if all(not s["budget_sufficient"] for s in shortlist):
                min_sup = min(shortlist, key=lambda x: x["total_price_in_req_currency"])
                min_unit = min_sup["unit_price_standard"]
                max_units_in_budget = (
                    int(budget_amount // convert(min_unit, min_sup["pricing_currency"], req_currency))
                    if quantity and quantity > 0 else None
                )
                add_issue(
                    "critical", "budget_insufficient",
                    (
                        f"Budget of {req_currency} {budget_amount:,.2f} cannot cover "
                        f"{quantity} {unit_of_measure} at any compliant supplier's pricing. "
                        f"Lowest available unit price is {min_sup['pricing_currency']} "
                        f"{min_unit:,.2f} ({min_sup['supplier_name']}, "
                        f"tier {min_sup['pricing_tier_applied']}), "
                        f"yielding a minimum total of {req_currency} {min_total:,.2f} — "
                        f"{req_currency} {min_total - budget_amount:,.2f} over budget."
                    ),
                    (
                        f"Requester must either increase budget to at least "
                        f"{req_currency} {min_total:,.2f}"
                        + (
                            f" or reduce quantity to a maximum of {max_units_in_budget} "
                            f"{unit_of_measure} within the stated budget."
                            if max_units_in_budget else "."
                        )
                    ),
                )

        # Policy conflict from NLP?
        if nlp_policy_refusal and nlp_policy_refusal.get("refusal_type") in (
            "no_exception_mandate", "skip_competitive_tender"
        ):
            add_issue(
                "high", "policy_conflict",
                (
                    f"Requester instruction '{nlp_policy_refusal.get('phrase')}' conflicts "
                    f"with policy: {tier.tier_id if tier else 'approval tier'} requires "
                    f"{required_quotes} quote(s). The requester cannot waive this unilaterally."
                ),
                f"Procurement policy must be applied. Deviation requires "
                f"{(tier.deviation_approval or ['Procurement Manager'])[0]} approval.",
            )

        # Lead time infeasible?
        if days_until_required is not None and shortlist and all(
            not s["lead_time_feasible"] for s in shortlist
        ):
            min_lt = min(s["lead_time_days"] for s in shortlist)
            max_lt = max(s["lead_time_days"] for s in shortlist)
            add_issue(
                "high", "lead_time_infeasible",
                (
                    f"Required delivery date {required_by_str} is {days_until_required} days "
                    f"from request creation. All {'expedited' if use_expedited else 'standard'} "
                    f"lead times for {category_l2} are {min_lt}–{max_lt} days. "
                    f"No compliant supplier can meet the stated deadline."
                ),
                "Requester must confirm whether the delivery date is a hard constraint. "
                "If so, no compliant supplier can meet it and an escalation is required.",
            )

        # NLP contradictions as issues
        for c in nlp_contradictions:
            if c.get("severity") in ("critical", "high"):
                add_issue(
                    c["severity"],
                    c["contradiction_type"].lower(),
                    c["description"],
                    c.get("recommended_action", "Confirm with requester."),
                )

        # Build policy_evaluation.preferred_supplier block
        pref_eval = None
        if preferred_named and preferred_supplier_status:
            pref_eval = {
                "supplier": preferred_named,
                "status": preferred_supplier_status.get("status", "unknown"),
                "is_preferred": preferred_supplier_status.get("is_on_preferred_list", False),
                "covers_delivery_country": preferred_supplier_status.get("status") not in (
                    "geography_mismatch", "not_found", "category_mismatch"
                ),
                "is_restricted": preferred_supplier_status.get("status") == "restricted",
                "policy_note": preferred_supplier_status.get("note", ""),
            }

        # Build policy_evaluation.restricted_suppliers block
        restricted_eval = {
            e.get("supplier_id", e.get("supplier_name", "unknown")): {
                "restricted": True,
                "reason": e["reason"][:120],
                "violation_detail": e.get("violation_detail", []),
            }
            for e in excluded
            if "Restriction" in e.get("reason", "")
        }

        # Compute minimum budget required
        min_budget_required = None
        min_budget_ccy = req_currency
        if shortlist and budget_amount is not None:
            cheapest = min(shortlist, key=lambda x: x["total_price_in_req_currency"])
            if not cheapest["budget_sufficient"]:
                min_budget_required = cheapest["total_price_in_req_currency"]

        # preferred_supplier_if_resolved: top compliant supplier when unblocked
        preferred_if_resolved = None
        if shortlist:
            preferred_if_resolved = shortlist[0]["supplier_name"]

        # Pricing tier summary string for audit trail
        tier_summary = ""
        if shortlist:
            tiers = list({s["pricing_tier_applied"] for s in shortlist})
            regions = list({s.get("req_currency","") for s in shortlist})
            tier_summary = (
                f"{tiers[0] if len(tiers)==1 else ', '.join(tiers)} "
                f"({delivery_region} region, {req_currency} currency)"
            )

        # Historical awards consulted?
        hist = historical_note
        hist_consulted = hist.get("has_direct_history", False) or (
            hist.get("similar_awards_count", 0) > 0
        )
        hist_note_str = ""
        if hist.get("has_direct_history"):
            awards_list = hist.get("prior_awards", [])
            if awards_list:
                ids = ", ".join(a.get("award_id","?") for a in awards_list[:3])
                hist_note_str = (
                    f"Direct history found: {ids}. "
                    "Award date is decision date, not delivery date. "
                    "Prior decision used for pattern context only."
                )
        elif hist.get("similar_awards_count", 0) > 0:
            hist_note_str = (
                f"{hist['similar_awards_count']} similar awards in same category/country. "
                f"Typical lead time: {hist.get('typical_lead_time_days','?')}d, "
                f"savings: {hist.get('typical_savings_pct','?')}%."
            )

        return {
            "request_id": req_id,
            "processed_at": now,
            "request_interpretation": {
                "category_l1": category_l1,
                "category_l2": category_l2,
                "quantity": quantity,
                "unit_of_measure": unit_of_measure,
                "budget_amount": budget_amount,
                "currency": req_currency,
                "delivery_country": delivery_countries[0] if len(delivery_countries) == 1 else None,
                "delivery_countries": delivery_countries,
                "delivery_region": delivery_region,
                "origin_country": origin_country,
                "required_by_date": required_by_str,
                "days_until_required": days_until_required,
                "data_residency_required": data_residency,
                "esg_requirement": esg_required,
                "preferred_supplier_stated": preferred_named,
                "incumbent_supplier": incumbent_named,
                "expedited_delivery_required": use_expedited,
                "requester_instruction": (
                    nlp_policy_refusal.get("phrase") if nlp_policy_refusal else None
                ),
                "nlp_filled_fields": nlp_filled if nlp_filled else None,
            },
            "validation": {
                "completeness": "fail" if (missing_fields or issues_detected) else "pass",
                "missing_fields": missing_fields,
                "issues_detected": issues_detected,
                "preferred_supplier_status": preferred_supplier_status,
            },
            "policy_evaluation": {
                "approval_threshold": {
                    "tier_id": tier.tier_id if tier else None,
                    "rule_applied": tier.tier_id if tier else None,
                    "threshold_currency": tier.currency if tier else None,
                    "effective_contract_value": round(effective_contract_value, 2),
                    "request_currency": req_currency,
                    "fx_conversion_notes": threshold_notes,
                    "quotes_required": required_quotes,
                    "fast_track_applied": fast_track_active,
                    "approvers": tier.approvers if tier else [],
                    "deviation_approval": tier.deviation_approval if tier else [],
                    "basis": (
                        f"All valid pricing options place total contract value at "
                        f"{req_currency} {effective_contract_value:,.2f}, "
                        f"which falls within {tier.tier_id} "
                        f"({tier.currency} {tier.min_amount:,.0f}–{tier.max_amount:,.0f})."
                        if tier else ""
                    ),
                    "note": threshold_notes if "BOUNDARY" in threshold_notes else "",
                },
                "preferred_supplier": pref_eval,
                "restricted_suppliers": restricted_eval if restricted_eval else {},
                "category_rules_applied": applicable_cat_rules,
                "geography_rules_applied": applicable_geo_rules,
            },
            "supplier_shortlist": shortlist,
            "suppliers_excluded": excluded,
            "escalations": escalations,
            "recommendation": {
                "status": status,
                "shortlist_count": len(shortlist),
                "quotes_required": required_quotes,
                "top_supplier": preferred_if_resolved,
                "top_supplier_total": (
                    shortlist[0]["total_price_in_req_currency"] if shortlist else None
                ),
                "all_infeasible_lead_time": (
                    all(not s["lead_time_feasible"] for s in shortlist)
                    if shortlist else None
                ),
                "all_over_budget": (
                    all(not s["budget_sufficient"] for s in shortlist)
                    if budget_amount and shortlist else None
                ),
                "preferred_supplier_if_resolved": preferred_if_resolved,
                "preferred_supplier_rationale": "",   # filled by rationale_generator
                "minimum_budget_required": min_budget_required,
                "minimum_budget_currency": min_budget_ccy if min_budget_required else None,
                "reason": "",   # filled by rationale_generator
            },
            "audit_trail": {
                "policies_checked": sorted(set(filter(None, policies_checked))),
                "supplier_ids_evaluated": list(candidate_ids),
                "pricing_region_used": delivery_region,
                "pricing_tiers_applied": tier_summary,
                "expedited_evaluated": use_expedited,
                "fx_rates_used": FX_TO_EUR,
                "data_sources_used": [
                    "../data/requests.json", "../data/merged_v2.csv", "../data/policies.json",
                ],
                "historical_awards_consulted": hist_consulted,
                "historical_award_note": hist_note_str,
                "historical_context": hist,
                "nlp_used": bool(request.get("nlp")),
                "nlp_translation_applied": nlp_translation is not None,
                "nlp_contradictions_detected": len(nlp_contradictions),
                "nlp_qty_override_applied": nlp_qty_override is not None,
                "nlp_fields_filled": list(nlp_filled.keys()) if nlp_filled else [],
            },
        }

    # ─────────────────────────────────────────────────────────────────────────
    # INTERNAL HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _check_preferred_supplier(
        self,
        preferred_named: str,
        category_l1: str,
        category_l2: str,
        delivery_countries: list[str],
        delivery_region: str,
        contract_value_eur: float,
        escalations: list,
        policies_checked: list,
    ) -> dict:
        """Validate the named preferred supplier against category, geography, restrictions."""
        # Find supplier ID by name in merged
        matches = self.merged[self.merged["supplier_name"] == preferred_named]
        if matches.empty:
            return {
                "supplier": preferred_named,
                "status": "not_found",
                "note": "Supplier not found in dataset — preference discarded.",
            }

        sup_id = matches.iloc[0]["supplier_id"]

        # Category match
        cat_match = self.merged[
            (self.merged["supplier_id"] == sup_id)
            & (self.merged["category_l2"] == category_l2)
        ]
        if cat_match.empty:
            actual_cats = self.merged[self.merged["supplier_id"] == sup_id]["category_l2"].unique()
            return {
                "supplier": preferred_named,
                "status": "category_mismatch",
                "note": (
                    f"'{preferred_named}' is not registered for {category_l2}. "
                    f"Registered categories: {list(actual_cats)}. Preference discarded."
                ),
            }

        # Geography
        service_regions = matches.iloc[0]["service_regions"]
        missing_countries = [
            c for c in delivery_countries
            if c not in service_regions.split(";")
        ]
        if missing_countries:
            return {
                "supplier": preferred_named,
                "status": "geography_mismatch",
                "missing_countries": missing_countries,
                "note": f"Does not serve {missing_countries}. Preference discarded.",
            }

        # Restrictions (FIX-06 + FIX-07)
        violations = _check_restrictions(
            sup_id, category_l1, category_l2,
            delivery_countries, contract_value_eur,
            self.indexes["rest_idx"],
        )
        if violations:
            escalations.append({
                "escalation_id": f"ESC-{len(escalations)+1:03d}",
                "rule": "ER-002",
                "trigger": (
                    f"Named preferred supplier '{preferred_named}' is restricted: "
                    + "; ".join(v["reason"] for v in violations)
                ),
                "escalate_to": "Procurement Manager",
                "blocking": False,
                "violations": violations,
            })
            policies_checked.append("ER-002")
            return {
                "supplier": preferred_named,
                "supplier_id": sup_id,
                "status": "restricted",
                "violations": violations,
                "note": "ER-002 escalation filed. Supplier excluded from shortlist.",
            }

        is_pref = _is_preferred(
            sup_id, category_l1, category_l2,
            delivery_region, self.indexes["pref_idx"]
        )
        return {
            "supplier": preferred_named,
            "supplier_id": sup_id,
            "status": "eligible",
            "is_on_preferred_list": is_pref,
            "note": (
                "Preferred status confirmed — included in shortlist. "
                "Preferred status is not a mandate; shortlist ranked on merit."
            ) if is_pref else (
                "Supplier is eligible but not on the preferred list for this category/region."
            ),
        }

    def _get_historical_context(
        self,
        request_id: str,
        category_l2: str,
        country: str,
    ) -> dict:
        """Pull historical award precedent for this request or similar context."""
        # Direct match
        direct = self.awards[self.awards["request_id"] == request_id]
        if not direct.empty:
            awarded = direct[direct["awarded"] == True]
            return {
                "has_direct_history": True,
                "prior_awards": awarded[
                    ["award_id", "supplier_name", "total_value", "currency",
                     "lead_time_days", "savings_pct", "escalation_required"]
                ].to_dict(orient="records"),
                "note": "Award date is decision date, not delivery date.",
            }

        # Category + country pattern
        similar = self.awards[
            (self.awards["category_l2"] == category_l2)
            & (self.awards["country"] == country)
            & (self.awards["awarded"] == True)
        ]
        if not similar.empty:
            return {
                "has_direct_history": False,
                "similar_awards_count": len(similar),
                "typical_lead_time_days": round(similar["lead_time_days"].mean(), 1),
                "typical_savings_pct": round(similar["savings_pct"].mean(), 1),
                "common_suppliers": similar["supplier_name"].value_counts().head(3).to_dict(),
                "note": "No direct history; pattern from similar awards in same category/country.",
            }

        return {"has_direct_history": False, "note": "No historical awards found for this category/country."}


# ══════════════════════════════════════════════════════════════════════════════
# 12.  BATCH RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def run_batch(
    requests_path: Path,
    data_dir: Path,
    output_path: Path,
    max_requests: int | None = None,
) -> list[dict]:
    engine = ProcurementRuleEngine(data_dir)
    requests = json.loads(requests_path.read_text())
    if max_requests:
        requests = requests[:max_requests]

    results = []
    errors = []
    for i, req in enumerate(requests):
        try:
            result = engine.process(req)
            results.append(result)
        except Exception as exc:
            errors.append({"request_id": req.get("request_id"), "error": str(exc)})
            print(f"  ERROR on {req.get('request_id')}: {exc}")

    output_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nProcessed {len(results)}/{len(requests)} requests → {output_path}")
    if errors:
        print(f"Errors: {len(errors)}")

    return results


# ══════════════════════════════════════════════════════════════════════════════
# 13.  QUICK VALIDATION REPORT
# ══════════════════════════════════════════════════════════════════════════════

def validation_report(results: list[dict]) -> None:
    """Print a summary of processing outcomes."""
    statuses = {}
    esc_rules = {}
    for r in results:
        s = r["recommendation"]["status"]
        statuses[s] = statuses.get(s, 0) + 1
        for e in r.get("escalations", []):
            rule = e.get("rule", "?")
            esc_rules[rule] = esc_rules.get(rule, 0) + 1

    print("\n" + "=" * 60)
    print("PROCESSING SUMMARY")
    print("=" * 60)
    print(f"Total requests processed: {len(results)}")
    print("\nOutcome distribution:")
    for s, c in sorted(statuses.items()):
        print(f"  {s}: {c}")
    print("\nEscalation rule frequency:")
    for r, c in sorted(esc_rules.items(), key=lambda x: -x[1]):
        print(f"  {r}: {c}")

    # Currency conversion cases
    fx_cases = [
        r["request_id"] for r in results
        if any(s.get("fx_applied") for s in r.get("supplier_shortlist", []))
    ]
    print(f"\nRequests with FX conversion applied: {len(fx_cases)}")

    # Capacity flags
    cap_flags = [
        r["request_id"] for r in results
        if any(s.get("capacity_flag") for s in r.get("supplier_shortlist", []))
    ]
    print(f"Requests with capacity flags: {len(cap_flags)}")
    print("=" * 60)


# ══════════════════════════════════════════════════════════════════════════════
# 14.  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    base = Path(__file__).parent
    data_dir = base  # assumes data files are in same directory as this script
    requests_path = data_dir / "../data/requests.json"
    output_path   = data_dir / "../data/output_v3.json"

    max_n = int(sys.argv[1]) if len(sys.argv) > 1 else None

    results = run_batch(requests_path, data_dir, output_path, max_n)
    validation_report(results)
