"""
build_merged.py  — ChainIQ START Hack 2026
==========================================
Builds merged_v2.csv: the flat supplier-pricing lookup table.

┌─────────────────────────────────────────────────────────────────┐
│  DESIGN EVALUATION: Is the flat-merge approach the right call?  │
└─────────────────────────────────────────────────────────────────┘

SHORT ANSWER: YES — with corrections and a clear understanding of
what should and should NOT live in this table.

WHAT THE MERGE GETS RIGHT
  • One row = one answerable question: "Can supplier X fulfil
    category Y in region Z at quantity tier Q, under which rules?"
  • Zero cross-referencing at query time — the rule engine does a
    single boolean mask and all facts are present.
  • Pricing tier selection is a pure row filter (min_qty ≤ qty ≤ max_qty).
  • Supplier-level facts (quality, risk, ESG, capacity, data residency)
    travel with every pricing row, so ranking needs no secondary lookup.

WHAT THE ORIGINAL merged.csv GOT WRONG (three bugs)
  BUG 1 — is_restricted_countries always NaN.
          Country-scoped restrictions from policies.json
          (SUP-0008 in CH/DE; SUP-0011 in CH; SUP-0017 in US/CA/AU/IN)
          were never written. Silently passes restricted suppliers.

  BUG 2 — data_residency_supported dropped.
          Essential for ER-005 (data residency conflict) and GR-001
          (Swiss sovereign cloud). Without it, a second join is needed.

  BUG 3 — No value-conditional restriction columns.
          SUP-0045 is restricted only ABOVE EUR 75k. The table had no
          threshold column, forcing runtime parsing of a free-text string.

WHAT MUST STAY OUT OF THE TABLE (evaluated at request time)
  • approval_thresholds  — depend on total contract value × quantity
  • geography_rules      — matched against per-request delivery_countries[]
  • escalation_rules     — condition-triggered, not row data

OUTPUT: 36 columns covering identity, capability, pricing tier,
        and three distinct restriction types + all review flags.
"""

import json
import re
import pandas as pd

SUPPLIERS_PATH = "../data/suppliers.csv"
PRICING_PATH   = "../data/pricing.csv"
POLICIES_PATH  = "../data/policies.json"
OUTPUT_PATH    = "../data/merged_v2.csv"

# Maps policy rule_type → output boolean column name
CATEGORY_RULE_COLS = {
    "security_review":         "requires_security_review",
    "cv_review":               "requires_cv_review",
    "brand_safety":            "requires_brand_safety",
    "engineering_spec_review": "requires_engineering_so",
    "mandatory_comparison":    "requires_mandatory_comparison",
}


# ═══════════════════════════════════════════════════════════════════════════
# 1.  POLICY INDEX BUILDERS
# ═══════════════════════════════════════════════════════════════════════════

def _parse_value_threshold(reason: str):
    """Extract first monetary threshold from a restriction reason string."""
    m = re.search(r"\b(EUR|CHF|USD)\s*([\d,]+)", reason)
    if m:
        return float(m.group(2).replace(",", "")), m.group(1)
    m = re.search(r"below\s+([\d,]+)\s+(EUR|CHF|USD)", reason, re.IGNORECASE)
    if m:
        return float(m.group(1).replace(",", "")), m.group(2).upper()
    return None, None


def build_preferred_index(policy):
    """{ (supplier_id, cat_l1, cat_l2) : {"regions": [...], "note": "..."} }"""
    idx = {}
    for e in policy["preferred_suppliers"]:
        key = (e["supplier_id"], e["category_l1"], e["category_l2"])
        idx[key] = {
            "regions": e.get("region_scope", []),
            "note":    e.get("policy_note", ""),
        }
    return idx


def build_restricted_index(policy):
    """
    { (supplier_id, cat_l1, cat_l2) : {
        is_global        : bool,   # blanket ban (no threshold)
        countries        : str,    # "CH;DE" | None
        value_conditional: bool,   # True = only restricted above threshold
        threshold        : float,  # 75000.0 | None
        threshold_ccy    : str,    # "EUR"   | None
        reason           : str,
    }}
    """
    idx = {}
    for e in policy["restricted_suppliers"]:
        key    = (e["supplier_id"], e["category_l1"], e["category_l2"])
        scope  = e.get("restriction_scope", [])
        reason = e.get("restriction_reason", "")
        threshold, tccy = _parse_value_threshold(reason)
        idx[key] = {
            "is_global":         scope == ["all"] and threshold is None,
            "countries":         None if scope == ["all"] else ";".join(scope),
            "value_conditional": threshold is not None,
            "threshold":         threshold,
            "threshold_ccy":     tccy,
            "reason":            reason,
        }
    return idx


def build_category_rules_index(policy):
    """{ (cat_l1, cat_l2) : {col_name: bool, ...} }"""
    defaults = {col: False for col in CATEGORY_RULE_COLS.values()}
    idx = {}
    for e in policy["category_rules"]:
        k   = (e["category_l1"], e["category_l2"])
        col = CATEGORY_RULE_COLS.get(e["rule_type"])
        if col:
            idx.setdefault(k, dict(defaults))
            idx[k][col] = True
    return idx


# ═══════════════════════════════════════════════════════════════════════════
# 2.  MAIN MERGE
# ═══════════════════════════════════════════════════════════════════════════

def build_merged():
    sup = pd.read_csv(SUPPLIERS_PATH)
    pri = pd.read_csv(PRICING_PATH)
    pol = json.load(open(POLICIES_PATH))

    print(f"  suppliers : {sup.shape[0]:>4} rows")
    print(f"  pricing   : {pri.shape[0]:>4} rows")

    pref_idx  = build_preferred_index(pol)
    rest_idx  = build_restricted_index(pol)
    cat_idx   = build_category_rules_index(pol)

    # ── Join pricing ← suppliers ────────────────────────────────────────────
    sup_cols = [
        "supplier_id", "supplier_name", "country_hq", "service_regions",
        "capacity_per_month", "data_residency_supported",
        "quality_score", "risk_score", "esg_score",
        "category_l1", "category_l2",
    ]
    pri_cols = [
        "supplier_id", "category_l1", "category_l2", "region",
        "pricing_model", "min_quantity", "max_quantity", "moq",
        "unit_price", "expedited_unit_price", "currency",
        "standard_lead_time_days", "expedited_lead_time_days",
        "valid_from", "valid_to",
    ]
    df = pri[pri_cols].merge(
        sup[sup_cols],
        on=["supplier_id", "category_l1", "category_l2"],
        how="left",
    ).rename(columns={
        "standard_lead_time_days":  "standard_lead_time",
        "expedited_lead_time_days": "expedited_lead_time",
    })

    # ── Preferred annotation ─────────────────────────────────────────────────
    is_pref, pref_scope = [], []
    for _, row in df.iterrows():
        e = pref_idx.get((row["supplier_id"], row["category_l1"], row["category_l2"]))
        if e and row["region"] in e["regions"]:
            is_pref.append(True)
            pref_scope.append(";".join(e["regions"]))
        else:
            is_pref.append(False)
            pref_scope.append(None)
    df["is_preferred"]        = is_pref
    df["preferred_region_scope"] = pref_scope

    # ── Restriction annotation (three distinct types) ─────────────────────
    r_global, r_countries, r_valcond, r_thresh, r_ccy, r_reason = \
        [], [], [], [], [], []

    for _, row in df.iterrows():
        e = rest_idx.get((row["supplier_id"], row["category_l1"], row["category_l2"]))
        if e:
            r_global.append(e["is_global"])
            r_countries.append(e["countries"])
            r_valcond.append(e["value_conditional"])
            r_thresh.append(e["threshold"])
            r_ccy.append(e["threshold_ccy"])
            r_reason.append(e["reason"])
        else:
            r_global.append(False)
            r_countries.append(None)
            r_valcond.append(False)
            r_thresh.append(None)
            r_ccy.append(None)
            r_reason.append(None)

    df["is_restricted_global"]            = r_global
    df["is_restricted_countries"]         = r_countries   # BUG FIX
    df["is_restricted_value_conditional"] = r_valcond     # NEW
    df["restriction_value_threshold"]     = r_thresh      # NEW
    df["restriction_currency"]            = r_ccy
    df["restriction_reason"]              = r_reason

    # ── Category rule flags ──────────────────────────────────────────────────
    defaults = {col: False for col in CATEGORY_RULE_COLS.values()}
    for col in CATEGORY_RULE_COLS.values():
        df[col] = [
            cat_idx.get((r["category_l1"], r["category_l2"]), defaults)[col]
            for _, r in df.iterrows()
        ]

    # ── Final column order ───────────────────────────────────────────────────
    return df[[
        "supplier_id", "supplier_name", "country_hq", "service_regions",
        "capacity_per_month", "data_residency_supported",
        "quality_score", "risk_score", "esg_score",
        "category_l1", "category_l2", "region",
        "pricing_model", "min_quantity", "max_quantity", "moq",
        "unit_price", "expedited_unit_price", "currency",
        "standard_lead_time", "expedited_lead_time",
        "valid_from", "valid_to",
        "is_preferred", "preferred_region_scope",
        "is_restricted_global",
        "is_restricted_countries",
        "is_restricted_value_conditional",
        "restriction_value_threshold",
        "restriction_currency",
        "restriction_reason",
        "requires_security_review",
        "requires_cv_review",
        "requires_brand_safety",
        "requires_engineering_so",
        "requires_mandatory_comparison",
    ]].reset_index(drop=True)


# ═══════════════════════════════════════════════════════════════════════════
# 3.  VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

def validate(df):
    results = []
    ok   = lambda m: results.append(f"  ✓  {m}")
    warn = lambda m: results.append(f"  ⚠  {m}")
    err  = lambda m: results.append(f"  ✗  {m}")

    ok(f"Total rows: {len(df)}")

    n_orphan = df["supplier_name"].isna().sum()
    (err if n_orphan else ok)(
        f"{n_orphan} orphan pricing rows (no matching supplier)"
        if n_orphan else "All pricing rows joined to a supplier"
    )

    # BUG FIX check
    n_country = df["is_restricted_countries"].notna().sum()
    (ok if n_country else err)(
        f"{n_country} rows carry country-scoped restrictions"
        if n_country else "is_restricted_countries entirely null — join failed"
    )

    n_val = df["is_restricted_value_conditional"].sum()
    (ok if n_val else warn)(
        f"{n_val} rows carry value-conditional restrictions"
        if n_val else "No value-conditional restrictions — check policies.json"
    )

    ok(f"{df['is_preferred'].sum()} rows flagged preferred")
    ok(f"{df['is_restricted_global'].sum()} rows flagged globally restricted")

    # data_residency_supported present (BUG FIX check)
    (ok if "data_residency_supported" in df.columns else err)(
        "data_residency_supported present"
        if "data_residency_supported" in df.columns
        else "data_residency_supported MISSING — ER-005 cannot be evaluated"
    )

    # Spot-check SUP-0008 Laptops → should have CH;DE
    mask = (df["supplier_id"] == "SUP-0008") & (df["category_l2"] == "Laptops")
    val  = df.loc[mask, "is_restricted_countries"].dropna().unique()
    if len(val) and "CH" in val[0]:
        ok(f"SUP-0008 Laptops restriction countries: {val[0]}")
    else:
        err("SUP-0008 Laptops country restriction not found")

    # Spot-check SUP-0045 → value threshold EUR 75000
    mask2 = df["supplier_id"] == "SUP-0045"
    tvals = df.loc[mask2, "restriction_value_threshold"].dropna().unique()
    if len(tvals):
        ok(f"SUP-0045 value threshold: {tvals[0]:,.0f} {df.loc[mask2,'restriction_currency'].dropna().iloc[0]}")
    else:
        err("SUP-0045 value threshold not found")

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 4.  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("ChainIQ — Building supplier-pricing lookup table")
    print("=" * 60)
    print("\nLoading sources…")

    merged = build_merged()
    print(f"\nMerged shape  : {merged.shape}")
    print(f"Columns ({len(merged.columns)})  : {list(merged.columns)}")

    print("\nValidation:")
    for msg in validate(merged):
        print(msg)

    merged.to_csv(OUTPUT_PATH, index=False)
    print(f"\nSaved → {OUTPUT_PATH}")
    print("=" * 60)
