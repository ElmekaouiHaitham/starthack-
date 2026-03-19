"""
rule_engine.py  — ChainIQ START Hack 2026
==========================================
Rule-based procurement policy engine.

INPUT  : merged_v2.csv  (built by build_merged.py)
         policies.json  (approval thresholds, geo rules, escalation rules)
         A single parsed request dict (see process_request())

OUTPUT : PolicyResult dataclass with
         - structured_request   — normalised fields extracted from the request
         - contradictions       — list of detected contradictions / missing data
         - supplier_shortlist   — ranked compliant suppliers with pricing
         - escalations          — triggered escalation rules
         - audit_trail          — ordered list of every rule evaluated

RULE COVERAGE
  ✓ ER-001  missing budget / quantity  → escalate to Requester
  ✓ ER-002  preferred supplier restricted → escalate to Procurement Manager
  ✓ ER-003  contract value exceeds tier → escalate to Head of Strategic Sourcing
  ✓ ER-004  no compliant supplier found → escalate to Head of Category
  ✓ ER-005  data residency conflict    → escalate to Security/Compliance
  ✓ ER-006  capacity exceeded          → escalate to Sourcing Excellence Lead
  ✓ ER-007  brand safety (Marketing)   → escalate to Marketing Governance Lead
  ✓ ER-008  USD supplier not screened  → escalate to Regional Compliance Lead
  ✓ CR-xxx  category-specific reviews (security, engineering, CV, brand safety)
  ✓ GR-xxx  geography rules (data sovereignty, lead time, language support)
  ✓ Approval tier + quote count determination
  ✓ Pricing tier selection (quantity → correct tier row)
  ✓ Preferred supplier preference enforcement (not mandate)
  ✓ Preferred supplier category / region mismatch detection
  ✓ Quantity ↔ request_text discrepancy flagging
  ✓ Incumbent supplier noted in shortlist

ARCHITECTURE NOTE
  This is a pure rule engine — no LLM calls, no heuristics.
  The AI layer (text parsing, language translation, ambiguity resolution)
  calls process_request() with an already-structured dict.
  Every decision is logged in audit_trail so an auditor can replay it.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

# ── Config ──────────────────────────────────────────────────────────────────
MERGED_PATH   = "../data/merged_v2.csv"
POLICIES_PATH = "../data/policies.json"

# Country → pricing region mapping
COUNTRY_REGION: dict[str, str] = {
    "DE": "EU", "FR": "EU", "NL": "EU", "BE": "EU", "AT": "EU",
    "IT": "EU", "ES": "EU", "PL": "EU", "UK": "EU", "CH": "EU",
    "US": "Americas", "CA": "Americas", "BR": "Americas", "MX": "Americas",
    "SG": "APAC", "AU": "APAC", "IN": "APAC", "JP": "APAC",
    "UAE": "MEA", "ZA": "MEA",
}

# Supplier ranking weights (must sum to 1.0)
W_PRICE   = 0.40   # lower unit price → higher score
W_QUALITY = 0.25   # quality_score / 100
W_RISK    = 0.20   # inverted risk_score (lower risk = better)
W_ESG     = 0.15   # esg_score / 100
PREF_BONUS = 0.05  # preferred supplier composite bonus


# ════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class StructuredRequest:
    request_id:                str
    category_l1:               str
    category_l2:               str
    quantity:                  float | None
    currency:                  str
    budget_amount:             float | None
    delivery_countries:        list[str]
    required_by_date:          str | None
    data_residency_constraint: bool
    esg_requirement:           bool
    preferred_supplier_id:     str | None
    preferred_supplier_name:   str | None
    incumbent_supplier:        str | None
    scenario_tags:             list[str]
    request_text:              str


@dataclass
class Escalation:
    rule_id:  str    # ER-001 … ER-008
    trigger:  str    # machine-readable trigger from policies.json
    target:   str    # human escalation target
    detail:   str    # request-specific context


@dataclass
class SupplierCandidate:
    supplier_id:     str
    supplier_name:   str
    region:          str
    unit_price:      float
    expedited_price: float
    total_value:     float
    standard_lead:   int
    expedited_lead:  int
    currency:        str
    quality_score:   float
    risk_score:      float
    esg_score:       float
    capacity:        float
    data_residency:  bool
    is_preferred:    bool
    is_incumbent:    bool
    composite_score: float
    rank:            int
    notes:           list[str]


@dataclass
class PolicyResult:
    request_id:         str
    structured_request: StructuredRequest
    contradictions:     list[str]
    escalations:        list[Escalation]
    approval_tier:      dict | None
    required_quotes:    int
    approvers:          list[str]
    supplier_shortlist: list[SupplierCandidate]
    audit_trail:        list[str]


# ════════════════════════════════════════════════════════════════════════════
# ENGINE
# ════════════════════════════════════════════════════════════════════════════

class PolicyEngine:
    """
    Load once, call process_request() repeatedly.
    All state is read-only after __init__.
    """

    def __init__(self, merged_path: str = MERGED_PATH,
                 policies_path: str = POLICIES_PATH):
        self.merged = pd.read_csv(merged_path)
        self.policy = json.load(open(policies_path))

        # Pre-index policy sections for O(1) access
        self._thresholds = self.policy["approval_thresholds"]
        self._geo_index  = self._index_geo_rules()
        self._esc_index  = {r["rule_id"]: r
                            for r in self.policy["escalation_rules"]}

    # ── Public API ───────────────────────────────────────────────────────────

    def process_request(self, req: dict) -> PolicyResult:
        """
        Full policy evaluation of one parsed request.

        Parameters
        ----------
        req : dict
            Keys mirror requests.json fields. Nullable fields may be absent
            or None; the engine handles both gracefully.

        Returns
        -------
        PolicyResult
        """
        trail: list[str] = []
        log = trail.append

        sr = self._build_structured_request(req, log)
        log(f"[INIT] {sr.request_id} — {sr.category_l1}/{sr.category_l2} "
            f"qty={sr.quantity} budget={sr.budget_amount} {sr.currency}")

        contradictions: list[str] = []
        escalations:    list[Escalation] = []

        # ── 1. Completeness + contradiction checks ───────────────────────────
        self._check_completeness(sr, contradictions, escalations, log)
        self._check_contradictions(sr, contradictions, log)

        # ── 2. Delivery region derivation ────────────────────────────────────
        regions = self._delivery_regions(sr, log)

        # ── 3. Build initial candidate pool ──────────────────────────────────
        candidates = self._build_candidate_pool(sr, regions, log)

        # ── 4. Apply restriction rules ───────────────────────────────────────
        candidates = self._filter_restricted(sr, candidates, escalations, log)

        # ── 5. Validate preferred supplier claim ─────────────────────────────
        self._check_preferred_supplier(sr, candidates, escalations, log)

        # ── 6. Capacity checks ───────────────────────────────────────────────
        self._check_capacity(sr, candidates, escalations, log)

        # ── 7. Data residency filter ─────────────────────────────────────────
        if sr.data_residency_constraint:
            candidates = self._filter_data_residency(
                sr, candidates, escalations, log)

        # ── 8. Geography rules (advisory, logged + attached to rows) ─────────
        self._apply_geography_rules(sr, candidates, escalations, log)

        # ── 9. Category review flags ──────────────────────────────────────────
        self._apply_category_rules(sr, candidates, log)

        # ── 10. Brand safety (Marketing category) ────────────────────────────
        if sr.category_l1 == "Marketing":
            self._check_brand_safety(sr, candidates, escalations, log)

        # ── 11. USD supplier sanction screening ──────────────────────────────
        self._check_usd_screening(sr, candidates, escalations, log)

        # ── 12. No compliant supplier ─────────────────────────────────────────
        if not candidates:
            escalations.append(Escalation(
                rule_id="ER-004",
                trigger="no_compliant_supplier_found",
                target="Head of Category",
                detail=(f"No compliant supplier for {sr.category_l2} "
                        f"in regions {regions} after all policy filters"),
            ))
            log("[ER-004] No compliant supplier — escalating to Head of Category")

        # ── 13. Approval tier + value ─────────────────────────────────────────
        total_value = self._calculate_total_value(sr, candidates, log)
        tier, quotes, approvers = self._approval_tier(
            total_value, sr.currency, log)

        # ── 14. ER-003: high-value escalation ────────────────────────────────
        self._check_high_value_escalation(
            tier, total_value, sr.currency, escalations, log)

        # ── 15. Rank + score ──────────────────────────────────────────────────
        shortlist = self._rank_candidates(sr, candidates, log)

        log(f"[DONE] {len(shortlist)} supplier(s) ranked, "
            f"{len(escalations)} escalation(s) triggered")

        return PolicyResult(
            request_id=sr.request_id,
            structured_request=sr,
            contradictions=contradictions,
            escalations=escalations,
            approval_tier=tier,
            required_quotes=quotes,
            approvers=approvers,
            supplier_shortlist=shortlist,
            audit_trail=trail,
        )

    # ════════════════════════════════════════════════════════════════════════
    # STEP IMPLEMENTATIONS
    # ════════════════════════════════════════════════════════════════════════

    def _build_structured_request(self, req: dict, log) -> StructuredRequest:
        # Normalise delivery_countries
        dc_raw = req.get("delivery_countries") or [req.get("country", "")]
        if isinstance(dc_raw, str):
            dc_raw = [c.strip() for c in
                      dc_raw.strip("[]").replace('"', "").split(",")]
        delivery_countries = [c.strip().upper() for c in dc_raw if c.strip()]

        # Resolve preferred supplier to an ID via master data
        pref_name = req.get("preferred_supplier_mentioned")
        pref_id   = None
        if pref_name:
            match = self.merged[
                self.merged["supplier_name"].str.lower() == pref_name.lower()
            ]
            pref_id = match.iloc[0]["supplier_id"] if not match.empty else None
            if not pref_id:
                log(f"[PREF] '{pref_name}' not found in supplier master")

        return StructuredRequest(
            request_id=req.get("request_id", "UNKNOWN"),
            category_l1=req.get("category_l1", ""),
            category_l2=req.get("category_l2", ""),
            quantity=req.get("quantity"),
            currency=req.get("currency", "EUR"),
            budget_amount=req.get("budget_amount"),
            delivery_countries=delivery_countries,
            required_by_date=req.get("required_by_date"),
            data_residency_constraint=bool(req.get("data_residency_constraint")),
            esg_requirement=bool(req.get("esg_requirement")),
            preferred_supplier_id=pref_id,
            preferred_supplier_name=pref_name,
            incumbent_supplier=req.get("incumbent_supplier"),
            scenario_tags=req.get("scenario_tags") or [],
            request_text=req.get("request_text", ""),
        )

    # ── 1. Completeness ──────────────────────────────────────────────────────

    def _check_completeness(self, sr, contradictions, escalations, log):
        missing = []
        if sr.budget_amount is None:
            missing.append("budget_amount")
        if sr.quantity is None:
            missing.append("quantity")
        if not sr.category_l2:
            missing.append("category_l2")
        if not sr.delivery_countries:
            missing.append("delivery_countries")

        if missing:
            msg = f"Missing required fields: {', '.join(missing)}"
            contradictions.append(msg)
            escalations.append(Escalation(
                rule_id="ER-001",
                trigger="missing_required_information",
                target="Requester Clarification",
                detail=msg,
            ))
            log(f"[ER-001] {msg}")

    # ── 2. Contradiction detection ───────────────────────────────────────────

    def _check_contradictions(self, sr, contradictions, log):
        text = sr.request_text.lower()

        # Quantity field vs quantities mentioned in free text
        if sr.quantity is not None:
            qty_in_text = re.findall(
                r"\b(\d+)\s*(?:units?|laptops?|devices?|licen[sc]es?|"
                r"seats?|pcs?|nodes?|monitors?|desktops?|workstations?)\b",
                text,
            )
            text_qtys = [int(n) for n in qty_in_text]
            if text_qtys and all(
                abs(q - sr.quantity) / max(sr.quantity, 1) > 0.15
                for q in text_qtys
            ):
                msg = (f"Quantity field ({int(sr.quantity)}) does not match "
                       f"quantities in request text {text_qtys}")
                contradictions.append(msg)
                log(f"[CONTRADICTION] {msg}")

        # Explicit refusal of a mandatory procurement step
        refusal_phrases = [
            "no competitive", "skip the rfp", "no rfp", "without tendering",
            "waive the process", "direct award only", "no need to compare",
            "no tender", "no quotes needed",
        ]
        for phrase in refusal_phrases:
            if phrase in text:
                msg = (f"Request text contains policy-conflicting phrase: "
                       f"'{phrase}'")
                contradictions.append(msg)
                log(f"[CONTRADICTION] {msg}")

    # ── 3. Delivery regions ──────────────────────────────────────────────────

    def _delivery_regions(self, sr, log) -> list[str]:
        regions = list({
            COUNTRY_REGION.get(c, "EU") for c in sr.delivery_countries
        })
        if not regions:
            regions = ["EU"]
        log(f"[GEO] {sr.delivery_countries} → pricing regions {regions}")
        return regions

    # ── 4. Candidate pool ────────────────────────────────────────────────────

    def _build_candidate_pool(self, sr, regions, log) -> list[dict]:
        m = self.merged

        # Category filter
        pool = m[
            (m["category_l1"] == sr.category_l1) &
            (m["category_l2"] == sr.category_l2)
        ].copy()
        log(f"[POOL] {len(pool)} rows match category {sr.category_l2}")

        if pool.empty:
            log(f"[POOL] No suppliers exist for {sr.category_l1}/{sr.category_l2}")
            return []

        # Region filter
        pool = pool[pool["region"].isin(regions)]
        log(f"[POOL] {len(pool)} rows after region filter {regions}")

        # Quantity tier filter
        if sr.quantity is not None:
            qty = sr.quantity
            pool = pool[
                (pool["min_quantity"] <= qty) & (pool["max_quantity"] >= qty)
            ]
            log(f"[POOL] {len(pool)} rows after qty tier filter (qty={qty})")
        else:
            # No quantity — use the lowest (MOQ) tier so we still get prices
            pool = pool[pool["min_quantity"] == pool["moq"]]
            log("[POOL] No quantity provided — using MOQ tier")

        # Service region coverage: supplier must cover at least one delivery country
        def covers(row):
            svc = str(row.get("service_regions", "")).upper().split(";")
            svc = [s.strip() for s in svc]
            return any(c in svc for c in sr.delivery_countries)

        before = len(pool)
        pool = pool[pool.apply(covers, axis=1)]
        log(f"[POOL] {len(pool)} rows after service-region coverage check "
            f"(dropped {before - len(pool)})")

        return pool.to_dict("records")

    # ── 5. Restriction filtering ─────────────────────────────────────────────

    def _filter_restricted(self, sr, candidates, escalations, log) -> list[dict]:
        est_value = self._estimate_total_value(sr, candidates)
        kept, dropped = [], 0

        for row in candidates:
            sid  = row["supplier_id"]
            cat2 = row["category_l2"]
            remove = False

            # Global (blanket) restriction
            if row.get("is_restricted_global"):
                log(f"[RESTRICT] {sid} globally restricted in {cat2} — removed")
                remove = True

            # Country-scoped restriction
            if not remove:
                rc = row.get("is_restricted_countries")
                if rc and not (isinstance(rc, float) and math.isnan(rc)):
                    restr_set = {c.strip().upper()
                                 for c in str(rc).split(";") if c.strip()}
                    hit = [c for c in sr.delivery_countries if c in restr_set]
                    if hit:
                        log(f"[RESTRICT] {sid} restricted in {hit} "
                            f"for {cat2} — removed")
                        remove = True

            # Value-conditional restriction
            if not remove and row.get("is_restricted_value_conditional"):
                thresh = row.get("restriction_value_threshold")
                thresh_ccy = row.get("restriction_currency", sr.currency)
                if thresh and est_value and est_value > thresh:
                    log(f"[RESTRICT] {sid} value-conditional restriction: "
                        f"est. {est_value:,.0f} > {thresh:,.0f} {thresh_ccy} "
                        f"— requires exception, flagged but kept")
                    row = dict(row)
                    row["_exception_required"] = (
                        f"Est. contract value {est_value:,.0f} {sr.currency} "
                        f"exceeds {thresh:,.0f} {thresh_ccy} — "
                        f"exception approval required before award"
                    )

            if remove:
                dropped += 1
            else:
                kept.append(row)

        log(f"[RESTRICT] Removed {dropped} restricted supplier(s), "
            f"{len(kept)} remaining")
        return kept

    # ── 6. Preferred supplier check ──────────────────────────────────────────

    def _check_preferred_supplier(self, sr, candidates, escalations, log):
        if not sr.preferred_supplier_name:
            return

        pname = sr.preferred_supplier_name
        pid   = sr.preferred_supplier_id

        # Is the named supplier registered for this category at all?
        in_cat = self.merged[
            (self.merged["supplier_name"].str.lower() == pname.lower()) &
            (self.merged["category_l1"] == sr.category_l1) &
            (self.merged["category_l2"] == sr.category_l2)
        ]
        if in_cat.empty:
            any_sup = self.merged[
                self.merged["supplier_name"].str.lower() == pname.lower()
            ]
            if not any_sup.empty:
                actual = any_sup["category_l2"].unique().tolist()
                log(f"[PREF] '{pname}' not registered for {sr.category_l2} "
                    f"(is in: {actual}) — preference discarded as category mismatch")
            else:
                log(f"[PREF] '{pname}' unknown in supplier master — discarded")
            return

        # Does the supplier cover the delivery region?
        regions_served = in_cat["region"].unique().tolist()
        req_regions    = self._delivery_regions(sr, lambda _: None)
        if not any(r in regions_served for r in req_regions):
            log(f"[PREF] '{pname}' does not serve regions {req_regions} "
                f"for {sr.category_l2} — preference discarded as region mismatch")
            return

        # Did the preferred supplier survive restriction filtering?
        pref_present = pid and any(r["supplier_id"] == pid for r in candidates)
        if not pref_present and pid:
            escalations.append(Escalation(
                rule_id="ER-002",
                trigger="preferred_supplier_restricted",
                target="Procurement Manager",
                detail=(f"Requester-preferred supplier '{pname}' ({pid}) "
                        f"was removed by a restriction rule for {sr.category_l2}"),
            ))
            log(f"[ER-002] Preferred supplier '{pname}' removed by restriction "
                "— escalating to Procurement Manager")
        elif pref_present:
            log(f"[PREF] '{pname}' is preferred, compliant, and in shortlist "
                "— will receive ranking bonus")

    # ── 7. Capacity ──────────────────────────────────────────────────────────

    def _check_capacity(self, sr, candidates, escalations, log):
        if sr.quantity is None:
            return
        seen: set[str] = set()
        for row in candidates:
            sid = row["supplier_id"]
            if sid in seen:
                continue
            seen.add(sid)
            cap = row.get("capacity_per_month", 0) or 0
            if cap and sr.quantity > cap:
                escalations.append(Escalation(
                    rule_id="ER-006",
                    trigger="single_supplier_capacity_risk",
                    target="Sourcing Excellence Lead",
                    detail=(f"{row['supplier_name']} monthly capacity "
                            f"{cap:,.0f} < requested qty {sr.quantity:,.0f}"),
                ))
                log(f"[ER-006] {row['supplier_name']} capacity {cap:,.0f} "
                    f"< qty {sr.quantity:,.0f} — escalating")

    # ── 8. Data residency ────────────────────────────────────────────────────

    def _filter_data_residency(self, sr, candidates, escalations, log) -> list[dict]:
        compliant = [r for r in candidates if r.get("data_residency_supported")]
        dropped   = len(candidates) - len(compliant)
        log(f"[DR] {dropped} supplier(s) removed — no data residency support; "
            f"{len(compliant)} remain")

        if not compliant:
            escalations.append(Escalation(
                rule_id="ER-005",
                trigger="data_residency_constraint_conflict",
                target="Security and Compliance Review",
                detail=(f"No supplier supports data residency constraint "
                        f"for delivery in {sr.delivery_countries}"),
            ))
            log("[ER-005] No compliant data-residency supplier — escalating")
            # Return full list so downstream steps can still produce a shortlist
            # (with the caveat flagged in escalations)
            return candidates
        return compliant

    # ── 9. Geography rules ───────────────────────────────────────────────────

    def _apply_geography_rules(self, sr, candidates, escalations, log):
        triggered: set[str] = set()

        def attach(rule):
            rid  = rule["rule_id"]
            text = rule.get("rule_text") or rule.get("rule", "")
            if rid not in triggered:
                triggered.add(rid)
                log(f"[GEO] {rid} triggered: {text}")
            for row in candidates:
                row.setdefault("_geo_notes", [])
                note = f"{rid}: {text}"
                if note not in row["_geo_notes"]:
                    row["_geo_notes"].append(note)

        for country in sr.delivery_countries:
            rule = self._geo_index.get(country)
            if rule:
                attach(rule)

        req_regions = {COUNTRY_REGION.get(c, "") for c in sr.delivery_countries}
        for region_key, rule in self._geo_index.items():
            if region_key in req_regions:
                covered = set(rule.get("countries", []))
                if any(c in covered for c in sr.delivery_countries):
                    attach(rule)

    # ── 10. Category review flags ─────────────────────────────────────────────

    def _apply_category_rules(self, sr, candidates, log):
        if not candidates:
            return
        sample = candidates[0]
        review_map = {
            "requires_security_review":      "Security review required before award",
            "requires_cv_review":            "CV review required for all candidates",
            "requires_brand_safety":         "Brand safety check required",
            "requires_engineering_so":       "Engineering/CAD sign-off required",
            "requires_mandatory_comparison": "Mandatory competitive comparison required",
        }
        for col, note in review_map.items():
            if sample.get(col):
                log(f"[CAT] {note}")
                for row in candidates:
                    row.setdefault("_category_notes", [])
                    if note not in row["_category_notes"]:
                        row["_category_notes"].append(note)

    # ── 11. Brand safety ─────────────────────────────────────────────────────

    def _check_brand_safety(self, sr, candidates, escalations, log):
        if any(r.get("requires_brand_safety") for r in candidates):
            escalations.append(Escalation(
                rule_id="ER-007",
                trigger="brand_safety_review_needed",
                target="Marketing Governance Lead",
                detail=f"Category {sr.category_l2} requires brand safety "
                       "check before award",
            ))
            log("[ER-007] Brand safety review required — escalating to "
                "Marketing Governance Lead")

    # ── 12. USD sanction screening ───────────────────────────────────────────

    def _check_usd_screening(self, sr, candidates, escalations, log):
        usd_regions = {"Americas", "APAC", "MEA"}
        req_regions = {COUNTRY_REGION.get(c, "") for c in sr.delivery_countries}
        if not (req_regions & usd_regions):
            return
        already_escalated = False
        for row in candidates:
            if row.get("currency") == "USD" and not already_escalated:
                escalations.append(Escalation(
                    rule_id="ER-008",
                    trigger="Supplier not registered or sanctioned-screened "
                            "in delivery country",
                    target="Regional Compliance Lead",
                    detail=(f"{row['supplier_name']} (USD pricing) requires "
                            f"sanction screening for {sr.delivery_countries}"),
                ))
                log(f"[ER-008] USD supplier '{row['supplier_name']}' — "
                    "Regional Compliance Lead screening required")
                already_escalated = True

    # ── 13 + 14. Total value + approval tier ─────────────────────────────────

    def _estimate_total_value(self, sr, candidates) -> float | None:
        if sr.budget_amount:
            return sr.budget_amount
        if candidates and sr.quantity:
            prices = [r.get("unit_price", 0) for r in candidates
                      if r.get("unit_price")]
            if prices:
                return (sum(prices) / len(prices)) * sr.quantity
        return None

    def _calculate_total_value(self, sr, candidates, log) -> float | None:
        if sr.budget_amount:
            log(f"[VALUE] Stated budget: {sr.budget_amount:,.2f} {sr.currency}")
            return sr.budget_amount
        if candidates and sr.quantity:
            best_price = min(
                (r.get("unit_price", math.inf) for r in candidates), default=None
            )
            if best_price and best_price < math.inf:
                total = best_price * sr.quantity
                log(f"[VALUE] Estimated: {best_price} × {sr.quantity:,.0f} "
                    f"= {total:,.2f} {sr.currency}")
                return total
        log("[VALUE] Cannot determine total value — no budget and no qty/price")
        return None

    def _approval_tier(self, total_value, currency, log):
        if total_value is None:
            log("[TIER] Total value unknown — cannot determine tier")
            return None, 1, ["Business"]

        tiers = sorted(
            [t for t in self._thresholds if t["currency"] == currency],
            key=lambda t: t["min_amount"],
        )
        for tier in tiers:
            if tier["min_amount"] <= total_value <= tier["max_amount"]:
                mgr = [m.replace("_", " ").title() for m in tier["managed_by"]]
                log(f"[TIER] {tier['threshold_id']}: {total_value:,.2f} "
                    f"{currency} → {tier['min_supplier_quotes']} quotes, "
                    f"approvers: {mgr}")
                return tier, tier["min_supplier_quotes"], mgr

        # Exceeds all defined tiers → use top tier
        top = tiers[-1]
        mgr = [m.replace("_", " ").title() for m in top["managed_by"]]
        log(f"[TIER] Value {total_value:,.2f} {currency} exceeds all tiers "
            f"→ top tier {top['threshold_id']}, approvers: {mgr}")
        return top, top["min_supplier_quotes"], mgr

    def _check_high_value_escalation(self, tier, total_value, currency,
                                      escalations, log):
        if not tier or total_value is None:
            return
        # Tiers AT-004/009/014 = 500K–5M; AT-005/010/015 = >5M (per currency)
        high_tier_ids = {"AT-004", "AT-005", "AT-009", "AT-010", "AT-014", "AT-015"}
        if tier.get("threshold_id") in high_tier_ids:
            mgr = tier.get("managed_by", ["strategic_sourcing"])[-1]
            escalations.append(Escalation(
                rule_id="ER-003",
                trigger="value_exceeds_threshold",
                target=mgr.replace("_", " ").title(),
                detail=(f"Contract value {total_value:,.2f} {currency} "
                        f"requires {tier['min_supplier_quotes']} quotes and "
                        f"approval from: "
                        f"{', '.join(m.replace('_',' ').title() for m in tier['managed_by'])}"),
            ))
            log(f"[ER-003] High-value contract — escalating to "
                f"{mgr.replace('_', ' ').title()}")

    # ── 15. Ranking ───────────────────────────────────────────────────────────

    def _rank_candidates(self, sr, candidates, log) -> list[SupplierCandidate]:
        if not candidates:
            return []

        prices = [r.get("unit_price", 0) for r in candidates if r.get("unit_price")]
        max_p  = max(prices) if prices else 1
        min_p  = min(prices) if prices else 0
        p_rng  = max(max_p - min_p, 1e-9)

        scored = []
        for row in candidates:
            up    = row.get("unit_price", 0) or 0
            ep    = row.get("expedited_unit_price") or up * 1.08
            qty   = sr.quantity or 1
            tv    = up * qty

            p_score  = 1.0 - (up - min_p) / p_rng
            q_score  = (row.get("quality_score", 50) or 50) / 100.0
            r_score  = 1.0 - (row.get("risk_score", 50) or 50) / 100.0
            e_score  = (row.get("esg_score", 50) or 50) / 100.0

            comp = (W_PRICE * p_score + W_QUALITY * q_score +
                    W_RISK  * r_score + W_ESG     * e_score)

            is_pref = bool(row.get("is_preferred"))
            if is_pref:
                comp += PREF_BONUS

            # ESG requirement — small bonus for high ESG
            if sr.esg_requirement:
                comp += 0.02 * e_score

            # Collect human-readable notes
            notes = []
            if row.get("_exception_required"):
                notes.append(f"⚠  Exception: {row['_exception_required']}")
            for n in row.get("_category_notes", []):
                notes.append(f"CAT: {n}")
            for n in row.get("_geo_notes", []):
                notes.append(f"GEO: {n}")

            is_incumb = bool(
                sr.incumbent_supplier and
                sr.incumbent_supplier.lower() in row["supplier_name"].lower()
            )
            if is_incumb:
                notes.append("ℹ  Incumbent supplier")

            scored.append({
                "comp": comp, "row": row,
                "up": up, "ep": ep, "tv": tv,
                "is_pref": is_pref, "is_incumb": is_incumb, "notes": notes,
            })

        scored.sort(key=lambda x: x["comp"], reverse=True)

        shortlist = []
        for rank, s in enumerate(scored, start=1):
            row = s["row"]
            log(f"[RANK #{rank}] {row['supplier_id']} {row['supplier_name']} "
                f"score={s['comp']:.4f} price={s['up']} "
                f"{'★PREF' if s['is_pref'] else ''} "
                f"{'◆INCUMB' if s['is_incumb'] else ''}")
            shortlist.append(SupplierCandidate(
                supplier_id=row["supplier_id"],
                supplier_name=row["supplier_name"],
                region=row["region"],
                unit_price=s["up"],
                expedited_price=s["ep"],
                total_value=s["tv"],
                standard_lead=int(row.get("standard_lead_time") or 0),
                expedited_lead=int(row.get("expedited_lead_time") or 0),
                currency=row.get("currency", sr.currency),
                quality_score=row.get("quality_score", 0),
                risk_score=row.get("risk_score", 0),
                esg_score=row.get("esg_score", 0),
                capacity=row.get("capacity_per_month", 0) or 0,
                data_residency=bool(row.get("data_residency_supported")),
                is_preferred=s["is_pref"],
                is_incumbent=s["is_incumb"],
                composite_score=round(s["comp"], 4),
                rank=rank,
                notes=s["notes"],
            ))
        return shortlist

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _index_geo_rules(self) -> dict[str, dict]:
        idx = {}
        for r in self.policy["geography_rules"]:
            # Index by country (single country rules like CH, DE, FR, ES)
            if "country" in r:
                idx[r["country"].upper()] = r
            # Index by region name (Americas, APAC, MEA, LATAM)
            if "region" in r:
                idx[r["region"]] = r
        return idx


# ════════════════════════════════════════════════════════════════════════════
# OUTPUT FORMATTER
# ════════════════════════════════════════════════════════════════════════════

def format_result(result: PolicyResult, verbose: bool = False) -> str:
    """Render a PolicyResult as a human-readable, audit-ready report."""
    sr  = result.structured_request
    DIV = "─" * 70
    HDR = "═" * 70

    lines = [
        HDR,
        f"  PROCUREMENT DECISION — {result.request_id}",
        HDR,
        "",
        "  REQUEST SUMMARY",
        DIV,
        f"  Category      : {sr.category_l1} / {sr.category_l2}",
        f"  Quantity      : {int(sr.quantity) if sr.quantity else 'NOT PROVIDED'}",
        f"  Budget        : "
        f"{f'{sr.budget_amount:,.2f}' if sr.budget_amount else 'NOT PROVIDED'}"
        f" {sr.currency}",
        f"  Delivery      : {', '.join(sr.delivery_countries) or '—'}",
        f"  Required by   : {sr.required_by_date or '—'}",
        f"  Data residency: {sr.data_residency_constraint}",
        f"  ESG required  : {sr.esg_requirement}",
        f"  Pref supplier : {sr.preferred_supplier_name or '—'}",
        f"  Incumbent     : {sr.incumbent_supplier or '—'}",
        f"  Scenario tags : {', '.join(sr.scenario_tags) or '—'}",
        "",
    ]

    if result.contradictions:
        lines += ["  ⚠  CONTRADICTIONS / MISSING DATA", DIV]
        for c in result.contradictions:
            lines.append(f"     • {c}")
        lines.append("")

    if result.escalations:
        lines += ["  🔺 ESCALATIONS REQUIRED", DIV]
        for e in result.escalations:
            lines += [
                f"     [{e.rule_id}] → {e.target}",
                f"            Trigger : {e.trigger}",
                f"            Detail  : {e.detail}",
            ]
        lines.append("")

    tier_id = result.approval_tier.get("threshold_id") if result.approval_tier else "UNKNOWN"
    lines += [
        "  APPROVAL & GOVERNANCE",
        DIV,
        f"  Tier            : {tier_id}",
        f"  Required quotes : {result.required_quotes}",
        f"  Approvers       : {', '.join(result.approvers)}",
        "",
    ]

    if result.supplier_shortlist:
        lines += ["  COMPLIANT SUPPLIER SHORTLIST", DIV]
        for s in result.supplier_shortlist:
            tags = ("  ★PREFERRED" if s.is_preferred else "") + \
                   ("  ◆INCUMBENT" if s.is_incumbent else "")
            lines += [
                f"  #{s.rank}  {s.supplier_id}  {s.supplier_name}{tags}",
                f"       Score   : {s.composite_score:.4f}",
                f"       Pricing : {s.unit_price:,.2f} {s.currency}/unit  "
                f"(expedited: {s.expedited_price:,.2f})  "
                f"Total: {s.total_value:,.2f}",
                f"       Lead    : {s.standard_lead}d standard  "
                f"/ {s.expedited_lead}d expedited",
                f"       Scores  : Quality {s.quality_score}  "
                f"Risk {s.risk_score}  ESG {s.esg_score}  "
                f"Capacity/mo {s.capacity:,.0f}",
            ]
            for note in s.notes:
                lines.append(f"       {note}")
        lines.append("")
    else:
        lines += ["  ⛔  NO COMPLIANT SUPPLIER IDENTIFIED", ""]

    if verbose:
        lines += ["  AUDIT TRAIL", DIV]
        for entry in result.audit_trail:
            lines.append(f"  {entry}")
        lines.append("")

    lines.append(HDR)
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════════
# SMOKE TEST  — three representative scenarios
# ════════════════════════════════════════════════════════════════════════════

SMOKE_TESTS = [
    {
        "_label": "STANDARD — EU laptop request, Dell preferred & incumbent",
        "request_id":  "TEST-001",
        "category_l1": "IT",
        "category_l2": "Laptops",
        "quantity":    150,
        "currency":    "EUR",
        "budget_amount": 145000,
        "delivery_countries": ["DE"],
        "data_residency_constraint": False,
        "esg_requirement": False,
        "preferred_supplier_mentioned": "Dell Enterprise Europe",
        "incumbent_supplier": "Dell Enterprise Europe",
        "required_by_date": "2026-04-15",
        "scenario_tags": ["standard"],
        "request_text": "Need 150 laptops for the Berlin office by April.",
    },
    {
        "_label": "RESTRICTED — Swiss cloud storage, AWS is restricted in CH",
        "request_id":  "TEST-002",
        "category_l1": "IT",
        "category_l2": "Cloud Storage",
        "quantity":    50,
        "currency":    "CHF",
        "budget_amount": 120000,
        "delivery_countries": ["CH"],
        "data_residency_constraint": True,
        "esg_requirement": False,
        "preferred_supplier_mentioned": "AWS Enterprise EMEA",
        "incumbent_supplier": None,
        "required_by_date": "2026-05-01",
        "scenario_tags": ["restricted"],
        "request_text": "Cloud storage for Swiss finance team, data must stay in CH.",
    },
    {
        "_label": "MISSING INFO — no budget, no quantity, ER-001 expected",
        "request_id":  "TEST-003",
        "category_l1": "IT",
        "category_l2": "Laptops",
        "quantity":    None,
        "currency":    "EUR",
        "budget_amount": None,
        "delivery_countries": ["FR"],
        "data_residency_constraint": False,
        "esg_requirement": False,
        "preferred_supplier_mentioned": None,
        "incumbent_supplier": None,
        "required_by_date": None,
        "scenario_tags": ["missing_info"],
        "request_text": "Need some laptops for the Paris team asap.",
    },
    {
        "_label": "CONTRADICTORY — quantity field vs text mismatch + direct-award refusal",
        "request_id":  "TEST-004",
        "category_l1": "IT",
        "category_l2": "Laptops",
        "quantity":    500,
        "currency":    "EUR",
        "budget_amount": 200000,
        "delivery_countries": ["NL"],
        "data_residency_constraint": False,
        "esg_requirement": True,
        "preferred_supplier_mentioned": None,
        "incumbent_supplier": None,
        "required_by_date": "2026-03-30",
        "scenario_tags": ["contradictory"],
        "request_text": (
            "We need 50 laptops for our Amsterdam office. "
            "No competitive process needed — direct award only to our usual vendor."
        ),
    },
]


if __name__ == "__main__":
    engine = PolicyEngine()

    for tc in SMOKE_TESTS:
        label = tc.pop("_label")
        print(f"\n{'#' * 70}")
        print(f"# {label}")
        print(f"{'#' * 70}")
        result = engine.process_request(dict(tc))  # copy so pop doesn't break reruns
        print(format_result(result, verbose=True))
