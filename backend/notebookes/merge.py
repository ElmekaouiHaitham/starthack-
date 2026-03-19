"""
merge.py
--------
Reads all 5 source files, produces one flat CSV: merged.csv
Run once: python merge.py
"""

import json, csv

# ── LOAD ───────────────────────────────────────────────────────────────────────

suppliers  = list(csv.DictReader(open("../data/suppliers.csv",  encoding="utf-8")))
pricing    = list(csv.DictReader(open("../data/pricing.csv",    encoding="utf-8")))
categories = list(csv.DictReader(open("../data/categories.csv", encoding="utf-8")))
policies   = json.load(open("../data/policies.json",            encoding="utf-8"))

# ── EXTRACT POLICY LOOKUPS ─────────────────────────────────────────────────────

# preferred_suppliers: list of {supplier_id, category_l1, category_l2, region}
preferred_set = set()
for p in policies.get("preferred_suppliers", []):
    key = (
        p.get("supplier_id","").strip(),
        p.get("category_l1","").strip().lower(),
        p.get("category_l2","").strip().lower(),
        p.get("region","").strip().upper(),
    )
    preferred_set.add(key)

# restricted_suppliers: keyed by supplier_id -> list of restriction rules
restricted_rules = {}
for r in policies.get("restricted_suppliers", []):
    sid = r.get("supplier_id","").strip()
    if sid not in restricted_rules:
        restricted_rules[sid] = []
    restricted_rules[sid].append(r)

# category_rules: keyed by category_l1 -> rule dict
cat_rules = policies.get("category_rules", [])

# ── BUILD SUPPLIER LOOKUP: supplier_id -> supplier row ─────────────────────────

supplier_lookup = {s["supplier_id"]: s for s in suppliers}

# ── MERGE ──────────────────────────────────────────────────────────────────────

merged_rows = []

for p in pricing:
    sid      = p.get("supplier_id","").strip()
    cat1     = p.get("category_l1","").strip()
    cat2     = p.get("category_l2","").strip()
    region   = p.get("region","").strip().upper()

    # Get the supplier master row
    s = supplier_lookup.get(sid)
    if not s:
        continue  # pricing row with no matching supplier — skip

    # ── preferred flag ─────────────────────────────────────────────────────────
    pref_key = (sid, cat1.lower(), cat2.lower(), region)
    # Also check without cat2 (some policies are at l1 level only)
    pref_key_l1 = (sid, cat1.lower(), "", region)
    is_preferred = (pref_key in preferred_set or pref_key_l1 in preferred_set)

    # Also check the preferred_supplier flag already on the supplier row
    if s.get("preferred_supplier","").lower() == "true":
        is_preferred = True

    # ── restriction rules for this supplier ────────────────────────────────────
    rules = restricted_rules.get(sid, [])

    is_restricted_global       = False
    is_restricted_countries    = []   # list of country codes
    is_restricted_above_value  = None # float or None
    restriction_currency       = None
    restriction_reason         = ""

    for r in rules:
        # Only apply if category matches (or rule has no category filter)
        r_cat1 = r.get("category_l1","").strip().lower()
        if r_cat1 and r_cat1 != cat1.lower():
            continue

        scope = r.get("scope","global")

        if scope == "global":
            is_restricted_global  = True
            restriction_reason    = r.get("reason","")

        elif scope == "country":
            is_restricted_countries += r.get("countries", [])
            restriction_reason = r.get("reason","")

        elif scope == "value_conditional":
            # Take the most restrictive threshold per currency
            for curr, val in r.get("threshold", {}).items():
                if (is_restricted_above_value is None or
                        float(val) < float(is_restricted_above_value)):
                    is_restricted_above_value = float(val)
                    restriction_currency      = curr
                    restriction_reason        = r.get("reason","")

    # Also check the is_restricted flag on the supplier row itself
    if s.get("is_restricted","").lower() == "true":
        is_restricted_global = True
        restriction_reason   = restriction_reason or s.get("restriction_reason","")

    # ── category rules ─────────────────────────────────────────────────────────
    cr = {}
    for rule in cat_rules:
        if isinstance(rule, dict) and rule.get("category_l1") == cat1:
            cr.update(rule)
    requires_security_review  = bool(cr.get("security_review_required",  False))
    requires_cv_review        = bool(cr.get("cv_review_required",        False))
    requires_brand_safety     = bool(cr.get("brand_safety_check",        False))
    requires_engineering_so   = bool(cr.get("engineering_signoff",       False))

    # ── build merged row ───────────────────────────────────────────────────────
    row = {
        # ── identity ──────────────────────────────────────────────────────────
        "supplier_id":           sid,
        "supplier_name":         s.get("supplier_name",""),
        "country_hq":            s.get("country_hq",""),
        "service_regions":       s.get("service_regions",""),
        "pricing_model":         s.get("pricing_model",""),
        "capacity_per_month":    s.get("capacity_per_month",""),

        # ── scores ────────────────────────────────────────────────────────────
        "quality_score":         s.get("quality_score",""),
        "risk_score":            s.get("risk_score",""),
        "esg_score":             s.get("esg_score",""),

        # ── category + region (defines when this row applies) ─────────────────
        "category_l1":           cat1,
        "category_l2":           cat2,
        "region":                region,

        # ── pricing ───────────────────────────────────────────────────────────
        "min_quantity":          p.get("min_quantity",""),
        "max_quantity":          p.get("max_quantity",""),
        "moq":                   p.get("moq",""),
        "unit_price":            p.get("unit_price",""),
        "expedited_unit_price":  p.get("expedited_unit_price",""),
        "currency":              p.get("currency",""),
        "standard_lead_time":    p.get("standard_lead_time_days",""),
        "expedited_lead_time":   p.get("expedited_lead_time_days",""),
        "valid_from":            p.get("valid_from",""),
        "valid_to":              p.get("valid_to",""),

        # ── preferred (from policies) ─────────────────────────────────────────
        "is_preferred":          is_preferred,

        # ── restrictions (from policies) ──────────────────────────────────────
        "is_restricted_global":       is_restricted_global,
        "is_restricted_countries":    ";".join(is_restricted_countries),
        "is_restricted_above_value":  is_restricted_above_value if is_restricted_above_value else "",
        "restriction_currency":       restriction_currency or "",
        "restriction_reason":         restriction_reason,

        # ── category compliance rules (from policies) ─────────────────────────
        "requires_security_review":   requires_security_review,
        "requires_cv_review":         requires_cv_review,
        "requires_brand_safety":      requires_brand_safety,
        "requires_engineering_so":    requires_engineering_so,
    }

    merged_rows.append(row)

# ── WRITE CSV ──────────────────────────────────────────────────────────────────

if not merged_rows:
    print("No rows produced — check your data files.")
else:
    fieldnames = list(merged_rows[0].keys())
    with open("../data/merged.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged_rows)

    print(f"Done. {len(merged_rows)} rows written to ../data/merged.csv")
    print(f"Unique suppliers : {len({r['supplier_id'] for r in merged_rows})}")
    print(f"Unique categories: {len({(r['category_l1'],r['category_l2']) for r in merged_rows})}")
    print(f"Globally restricted rows removed at query time (still in file, flagged)")
