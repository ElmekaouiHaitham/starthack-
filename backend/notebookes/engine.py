"""
engine.py
---------
Full rule-based procurement engine.
Reads requests.json + merged.csv + policies.json (approval tiers + escalation rules only).

Run:
  python engine.py                        # first 3 requests
  python engine.py REQ-000001             # single request
  python engine.py --tag=restricted       # first 3 with that tag
  python engine.py --batch=20             # first 20 requests
"""

import json, csv, re, sys
from datetime import datetime, date


# ══════════════════════════════════════════════════════════════════════════════
# 1. LOAD DATA
# ══════════════════════════════════════════════════════════════════════════════

requests = json.load(open("data/requests.json", encoding="utf-8"))
policies = json.load(open("data/policies.json", encoding="utf-8"))
merged   = list(csv.DictReader(open("data/merged.csv", encoding="utf-8")))
history  = list(csv.DictReader(open("data/historical_awards.csv", encoding="utf-8")))


# ══════════════════════════════════════════════════════════════════════════════
# 2. CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

# Approval thresholds: (ceiling, quotes_needed, approver)
TIERS = {
    "EUR": [
        (25_000,       1, "Business"),
        (100_000,      2, "Business + Procurement"),
        (500_000,      3, "Head of Category"),
        (5_000_000,    3, "Head of Strategic Sourcing"),
        (float("inf"), 3, "CPO"),
    ],
    "CHF": [
        (27_500,       1, "Business"),
        (110_000,      2, "Business + Procurement"),
        (550_000,      3, "Head of Category"),
        (5_500_000,    3, "Head of Strategic Sourcing"),
        (float("inf"), 3, "CPO"),
    ],
    "USD": [
        (27_000,       1, "Business"),
        (108_000,      2, "Business + Procurement"),
        (540_000,      3, "Head of Category"),
        (5_400_000,    3, "Head of Strategic Sourcing"),
        (float("inf"), 3, "CPO"),
    ],
}

# Country → pricing region
REGION_MAP = {
    "DE":"EU","FR":"EU","NL":"EU","BE":"EU","AT":"EU",
    "IT":"EU","ES":"EU","PL":"EU","UK":"EU","CH":"EU",
    "US":"Americas","CA":"Americas","BR":"Americas","MX":"Americas",
    "SG":"APAC","AU":"APAC","IN":"APAC","JP":"APAC",
    "UAE":"MEA","ZA":"MEA",
}

# Escalation targets
TARGETS = {
    "ER-001": "Requester",
    "ER-002": "Procurement Manager",
    "ER-003": "Head of Strategic Sourcing",
    "ER-004": "Head of Category",
    "ER-005": "Security / Compliance",
    "ER-006": "Sourcing Excellence Lead",
    "ER-007": "Marketing Governance Lead",
    "ER-008": "Regional Compliance Lead",
}


# ══════════════════════════════════════════════════════════════════════════════
# 3. HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def flt(val, default=0.0):
    """Safe float conversion."""
    try:
        return float(val) if val not in (None, "", "None") else default
    except (ValueError, TypeError):
        return default

def to_bool(val):
    """CSV booleans come as strings."""
    return str(val).strip().lower() in ("true", "1", "yes")

def parse_date(raw):
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None

def get_tier(budget, currency):
    """Return (tier_number, quotes_required, approver)."""
    for i, (ceiling, quotes, approver) in enumerate(
            TIERS.get(currency.upper(), TIERS["EUR"]), start=1):
        if float(budget) < ceiling:
            return i, quotes, approver
    return 5, 3, "CPO"

def get_region(countries):
    """Map first delivery country to a pricing region."""
    if not countries:
        return "EU"
    return REGION_MAP.get(str(countries[0]).upper(), "EU")


# ══════════════════════════════════════════════════════════════════════════════
# 4. STEP 1 — VALIDATE THE REQUEST
# ══════════════════════════════════════════════════════════════════════════════

def validate(req):
    """
    Returns a list of issues, each a dict:
      { severity: HIGH|MEDIUM, field: str, msg: str, er: str|None }
    """
    issues = []

    def flag(severity, field, msg, er=None):
        issues.append({"severity": severity, "field": field, "msg": msg, "er": er})

    # Missing budget
    if not req.get("budget_amount"):
        flag("HIGH", "budget_amount",
             "Budget missing — cannot calculate approval tier or validate pricing",
             "ER-001")

    # Missing quantity
    if not req.get("quantity"):
        flag("HIGH", "quantity",
             "Quantity missing — cannot calculate pricing or check capacity",
             "ER-001")

    # Missing deadline
    if not req.get("required_by_date"):
        flag("MEDIUM", "required_by_date",
             "No deadline provided — cannot check lead time feasibility")

    # Missing delivery country
    if not req.get("delivery_countries"):
        flag("HIGH", "delivery_countries",
             "No delivery country — cannot filter suppliers or apply geography rules",
             "ER-001")

    # Missing category
    if not req.get("category_l1"):
        flag("HIGH", "category_l1",
             "Category could not be determined from request",
             "ER-001")

    # Quantity contradiction: field vs free text
    qty  = req.get("quantity")
    text = req.get("request_text", "")
    if qty and text:
        nums = [int(n) for n in re.findall(r'\b(\d{1,6})\b', text)
                if 1 <= int(n) <= 999_999]
        if nums:
            closest = min(nums, key=lambda n: abs(n - float(qty)))
            if abs(closest - float(qty)) > float(qty) * 0.10:
                flag("MEDIUM", "quantity",
                     f"Quantity field is {qty} but request text mentions {closest} "
                     f"— possible contradiction, both surfaced for review")

    return issues


# ══════════════════════════════════════════════════════════════════════════════
# 5. STEP 2 — QUERY THE MERGED TABLE
# ══════════════════════════════════════════════════════════════════════════════

def query_suppliers(req, deadline):
    """
    Filters merged.csv to rows that match the request.
    Applies every restriction rule.
    Calculates exact pricing (standard vs expedited).
    Returns a list of option dicts — one per matching row.
    """
    cat1      = (req.get("category_l1") or "").strip().lower()
    cat2      = (req.get("category_l2") or "").strip().lower()
    qty       = flt(req.get("quantity"))
    currency  = (req.get("currency") or "EUR").upper()
    countries = req.get("delivery_countries") or []
    budget    = flt(req.get("budget_amount"))
    region    = get_region(countries)
    today     = date.today()
    options   = []

    for row in merged:

        # ── Category match ─────────────────────────────────────────────────────
        if row["category_l1"].strip().lower() != cat1:
            continue
        if row["category_l2"].strip().lower() != cat2:
            continue

        # ── Region match ───────────────────────────────────────────────────────
        if row["region"].strip().upper() != region.upper():
            continue

        # ── Geographic coverage: does supplier serve the delivery countries? ───
        service_regions = [r.strip() for r in row["service_regions"].split(";")]
        if countries and not any(c.upper() in service_regions for c in countries):
            continue

        # ── Global restriction: always skip ───────────────────────────────────
        if to_bool(row["is_restricted_global"]):
            continue

        # ── Country-scoped restriction ─────────────────────────────────────────
        restricted_countries = [c.strip() for c in row["is_restricted_countries"].split(";")
                                 if c.strip()]
        if restricted_countries:
            if any(c.upper() in restricted_countries for c in countries):
                continue  # delivery country is in the restricted list

        # ── Quantity tier match ────────────────────────────────────────────────
        min_q = flt(row["min_quantity"])
        max_q = flt(row["max_quantity"]) if row["max_quantity"] else float("inf")
        moq   = flt(row["moq"])

        if qty > 0:
            if not (min_q <= qty <= max_q):
                continue          # quantity not in this tier
            if qty < moq:
                continue          # below minimum order quantity

        # ── Value-conditional restriction (needs calculated price first) ───────
        unit_std = flt(row["unit_price"])
        unit_exp = flt(row["expedited_unit_price"]) or unit_std * 1.08
        std_lead = int(flt(row["standard_lead_time"]) or 30)
        exp_lead = int(flt(row["expedited_lead_time"]) or std_lead)

        # Choose standard vs expedited
        use_expedited = False
        if deadline:
            days_available = (deadline - today).days
            if days_available < std_lead:
                use_expedited = True

        active_unit  = unit_exp if use_expedited else unit_std
        active_lead  = exp_lead if use_expedited else std_lead
        total_price  = round(active_unit * max(qty, 1), 2)

        # Now check value-conditional restriction
        above_val = row.get("is_restricted_above_value","")
        if above_val:
            threshold       = flt(above_val)
            restrict_curr   = row.get("restriction_currency","").upper() or currency
            # Convert to same currency for comparison (simplified: assume same)
            if restrict_curr == currency and total_price > threshold:
                continue      # exceeds the value threshold — restricted

        # ── Capacity check (flag but do NOT discard) ───────────────────────────
        capacity = flt(row["capacity_per_month"]) or float("inf")
        cap_ok   = (qty <= capacity) if qty > 0 else True

        # ── Preferred flag ─────────────────────────────────────────────────────
        is_preferred = to_bool(row["is_preferred"])

        # ── Collect this option ────────────────────────────────────────────────
        options.append({
            "supplier_id":             row["supplier_id"],
            "supplier_name":           row["supplier_name"],
            "unit_price":              active_unit,
            "total_price":             total_price,
            "currency":                row["currency"] or currency,
            "lead_time":               active_lead,
            "expedited":               use_expedited,
            "quality":                 flt(row["quality_score"]),
            "risk":                    flt(row["risk_score"]),
            "esg":                     flt(row["esg_score"]),
            "is_preferred":            is_preferred,
            "capacity_ok":             cap_ok,
            "capacity_per_month":      capacity,
            # compliance flags — carry forward for escalation checks
            "requires_security_review":to_bool(row["requires_security_review"]),
            "requires_cv_review":      to_bool(row["requires_cv_review"]),
            "requires_brand_safety":   to_bool(row["requires_brand_safety"]),
            "requires_engineering_so": to_bool(row["requires_engineering_so"]),
            "pricing_tier":            f"{int(min_q)}–{int(max_q) if max_q != float('inf') else '+'}",
        })

    return options


# ══════════════════════════════════════════════════════════════════════════════
# 6. STEP 3 — CHECK PREFERRED SUPPLIER VALIDITY
# ══════════════════════════════════════════════════════════════════════════════

def check_preferred(preferred_name, cat1, cat2, countries):
    """
    Returns (status, detail).
    Status: NOT_MENTIONED | NOT_FOUND | WRONG_CATEGORY | WRONG_REGION | VALID
    """
    if not preferred_name:
        return "NOT_MENTIONED", ""

    name_lower = preferred_name.strip().lower()

    # Find all rows that mention this supplier
    all_matches = [r for r in merged
                   if name_lower in r["supplier_name"].lower()]

    if not all_matches:
        return "NOT_FOUND", (
            f"'{preferred_name}' is not in the approved supplier database. "
            f"Preference discarded.")

    # Check category match
    cat_matches = [r for r in all_matches
                   if r["category_l1"].lower() == cat1.lower()]
    if not cat_matches:
        actual = list({r["category_l1"] for r in all_matches})
        return "WRONG_CATEGORY", (
            f"'{preferred_name}' is registered under {actual}, not '{cat1}'. "
            f"Preference discarded.")

    # Check subcategory match
    sub_matches = [r for r in cat_matches
                   if r["category_l2"].lower() == cat2.lower()]
    pool = sub_matches or cat_matches

    # Check region coverage
    for r in pool:
        service_regions = [x.strip() for x in r["service_regions"].split(";")]
        if any(c.upper() in service_regions for c in countries):
            return "VALID", (
                f"'{preferred_name}' is in the approved supplier database "
                f"and covers the delivery region.")

    return "WRONG_REGION", (
        f"'{preferred_name}' does not cover delivery countries {countries}. "
        f"Preference discarded.")


# ══════════════════════════════════════════════════════════════════════════════
# 7. STEP 4 — RANK SUPPLIERS
# ══════════════════════════════════════════════════════════════════════════════

def rank(options, esg_required=False):
    """
    Weighted score:
      Price   40%  (lower price = higher score)
      Quality 30%
      Risk    20%  (lower risk = higher score)
      ESG     10%  (20% if esg_required)
      Preferred bonus  +5
      Capacity penalty -15
    Returns top 3 sorted by score descending.
    """
    if not options:
        return []

    prices = [o["total_price"] for o in options if o["total_price"] > 0]
    lo     = min(prices) if prices else 1
    hi     = max(prices) if prices else 1
    spread = (hi - lo) or 1
    esg_w  = 20 if esg_required else 10

    for o in options:
        price_sc   = ((hi - o["total_price"]) / spread) * 40
        quality_sc = (o["quality"] / 100) * 30
        risk_sc    = ((100 - o["risk"]) / 100) * 20
        esg_sc     = (o["esg"] / 100) * esg_w
        pref_bonus = 5  if o["is_preferred"]  else 0
        cap_pen    = -15 if not o["capacity_ok"] else 0

        o["score"] = round(price_sc + quality_sc + risk_sc
                           + esg_sc + pref_bonus + cap_pen, 1)

    return sorted(options, key=lambda o: o["score"], reverse=True)[:3]


# ══════════════════════════════════════════════════════════════════════════════
# 8. STEP 5 — FIRE ALL ESCALATION RULES
# ══════════════════════════════════════════════════════════════════════════════

def get_escalations(req, issues, shortlist, all_options, budget, currency, deadline):
    """
    Checks all 8 ER rules.
    Collects every one that fires — never stops at the first.
    Returns list of { rule, target, trigger, detail }.
    """
    esc   = []
    today = date.today()
    qty   = flt(req.get("quantity"))

    def add(rule, trigger, detail):
        esc.append({
            "rule":    rule,
            "target":  TARGETS[rule],
            "trigger": trigger,
            "detail":  detail,
        })

    # ── ER-001: missing required information ──────────────────────────────────
    er001 = [i for i in issues if i.get("er") == "ER-001"]
    if er001:
        fields = ", ".join(i["field"] for i in er001)
        detail = "; ".join(i["msg"] for i in er001)
        add("ER-001", f"Missing required fields: {fields}", detail)

    # ── ER-002: preferred supplier is restricted ──────────────────────────────
    preferred_name = req.get("preferred_supplier_mentioned","")
    if preferred_name:
        name_lower = preferred_name.strip().lower()
        pref_rows  = [r for r in merged
                      if name_lower in r["supplier_name"].lower()
                      and r["category_l1"].lower() == (req.get("category_l1") or "").lower()]
        for r in pref_rows:
            if to_bool(r["is_restricted_global"]):
                add("ER-002",
                    f"Preferred supplier '{preferred_name}' is globally restricted",
                    r.get("restriction_reason",""))
                break
            countries = req.get("delivery_countries") or []
            rc = [c.strip() for c in r["is_restricted_countries"].split(";") if c.strip()]
            overlap = [c for c in countries if c.upper() in rc]
            if overlap:
                add("ER-002",
                    f"Preferred supplier '{preferred_name}' is restricted in {overlap}",
                    r.get("restriction_reason",""))
                break
            above = r.get("is_restricted_above_value","")
            if above and budget and flt(above) > 0 and budget > flt(above):
                add("ER-002",
                    f"Preferred supplier '{preferred_name}' restricted above "
                    f"{r.get('restriction_currency',currency)} {flt(above):,.0f}",
                    r.get("restriction_reason",""))
                break

    # ── ER-003: contract value exceeds senior threshold ───────────────────────
    if budget:
        tier, _, approver = get_tier(budget, currency)
        if tier >= 4:
            add("ER-003",
                f"Contract value {currency} {budget:,.0f} is Tier {tier} — requires senior approval",
                f"Route to: {approver}. {get_tier(budget, currency)[1]} quotes required.")

    # ── ER-004: no compliant supplier found ───────────────────────────────────
    if not all_options:
        add("ER-004",
            "No compliant supplier identified",
            "Zero suppliers passed all filters (category, region, restrictions, quantity tier). "
            "Manual sourcing required.")

    # ── ER-005: data residency constraint ─────────────────────────────────────
    if req.get("data_residency_constraint"):
        add("ER-005",
            "Data residency constraint declared on this request",
            "Verify that every shortlisted supplier holds data exclusively within "
            "the delivery country. Escalate immediately if confirmation cannot be obtained.")

    # ── ER-006: quantity exceeds ALL supplier capacities ─────────────────────
    if qty and all_options:
        all_over_capacity = all(not o["capacity_ok"] for o in all_options)
        if all_over_capacity:
            max_cap = max(o["capacity_per_month"] for o in all_options)
            add("ER-006",
                f"Requested quantity {qty:,.0f} exceeds every supplier's monthly capacity "
                f"(max available: {max_cap:,.0f})",
                "Options: split order across multiple suppliers, request phased delivery, "
                "or extend the timeline.")

    # ── ER-007: Marketing category always requires brand safety ───────────────
    if (req.get("category_l1") or "").strip().lower() == "marketing":
        add("ER-007",
            "Marketing category — brand safety review mandatory",
            "All Marketing awards must be reviewed by Marketing Governance Lead "
            "before contract execution.")

    # ── ER-008: deadline is physically impossible ─────────────────────────────
    if deadline and all_options:
        days_available = (deadline - today).days
        fastest        = min(o["lead_time"] for o in all_options)
        if days_available < fastest:
            add("ER-008",
                f"Deadline in {days_available} day(s) — fastest available supplier needs {fastest} day(s)",
                "Recommend: (1) check local stock with shortlisted suppliers, "
                "(2) consider partial delivery by deadline + remainder later, "
                "(3) negotiate deadline extension with requester.")

    # ── Category compliance escalations (from merged table) ───────────────────
    # These are not ER rules but must be surfaced
    comp_flags = []
    if shortlist:
        s = shortlist[0]  # check top recommended supplier
        if s.get("requires_security_review"):
            comp_flags.append("IT Security review required before award")
        if s.get("requires_cv_review"):
            comp_flags.append("CV review of proposed consultant required before award")
        if s.get("requires_engineering_so"):
            comp_flags.append("Engineering sign-off required before award")

    if comp_flags:
        add("ER-002",  # closest match — procurement manager owns compliance steps
            "Category compliance steps required before award",
            " | ".join(comp_flags))

    return esc


# ══════════════════════════════════════════════════════════════════════════════
# 9. STEP 6 — CONFIDENCE SCORE
# ══════════════════════════════════════════════════════════════════════════════

def confidence(issues, shortlist, escalations, budget, currency):
    score = 100

    # Deduct per issue severity
    for i in issues:
        score -= 20 if i["severity"] == "HIGH" else 10

    # Deduct per escalation (except ER-007 which is always expected for Marketing)
    score -= len([e for e in escalations if e["rule"] != "ER-007"]) * 5

    # No suppliers found is severe
    if not shortlist:
        score -= 30

    # Budget near an approval tier boundary — small contract value change
    # could move entire approval chain, so confidence is lower
    if budget:
        for ceiling, _, _ in TIERS.get(currency, TIERS["EUR"]):
            if ceiling != float("inf"):
                if abs(budget - ceiling) / ceiling < 0.05:
                    score -= 10
                    break

    return max(0, min(100, score))


# ══════════════════════════════════════════════════════════════════════════════
# 10. STEP 7 — HISTORICAL PRECEDENTS
# ══════════════════════════════════════════════════════════════════════════════

def get_precedents(req, n=3):
    """
    Finds n most similar past awards.
    Scores by: budget proximity (0–2) + policy compliant flag (+1).
    Only looks at rows where awarded = True.
    """
    budget  = flt(req.get("budget_amount"))
    awarded = [h for h in history if h.get("awarded","").lower() == "true"]

    def sim(h):
        s = 1 if h.get("policy_compliant","").lower() == "true" else 0
        v = flt(h.get("total_value"))
        if budget and v:
            s += min(budget, v) / max(budget, v) * 2
        return s

    return sorted(awarded, key=sim, reverse=True)[:n]


# ══════════════════════════════════════════════════════════════════════════════
# 11. MAIN PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def analyze(req):
    currency  = (req.get("currency") or "EUR").upper()
    budget    = flt(req.get("budget_amount"))
    countries = req.get("delivery_countries") or []
    esg       = bool(req.get("esg_requirement", False))
    deadline  = parse_date(req.get("required_by_date"))

    # 1. Validate
    issues = validate(req)

    # 2. Query merged table → all valid options
    all_opts = query_suppliers(req, deadline)

    # 3. Check preferred supplier validity
    preferred_name   = req.get("preferred_supplier_mentioned","")
    pref_status, pref_detail = check_preferred(
        preferred_name,
        req.get("category_l1",""),
        req.get("category_l2",""),
        countries
    )

    # 4. Rank top 3
    shortlist = rank(all_opts, esg)

    # 5. Approval tier
    tier, quotes, approver = get_tier(budget, currency) if budget else (None, None, None)

    # 6. Escalations (all 8 rules)
    escalations = get_escalations(
        req, issues, shortlist, all_opts, budget, currency, deadline
    )

    # 7. Confidence
    score = confidence(issues, shortlist, escalations, budget, currency)

    # 8. Historical precedents
    precedents = get_precedents(req)

    return {
        "request_id":    req.get("request_id", "UNKNOWN"),
        "confidence":    score,
        "category":      f"{req.get('category_l1')}/{req.get('category_l2')}",
        "quantity":      req.get("quantity"),
        "budget":        budget or None,
        "currency":      currency,
        "countries":     countries,
        "deadline":      str(deadline) if deadline else None,
        "esg_required":  esg,
        "preferred": {
            "name":   preferred_name or None,
            "status": pref_status,
            "detail": pref_detail,
        },
        "approval": {
            "tier":    tier,
            "quotes":  quotes,
            "approver":approver,
        },
        "issues":       issues,
        "shortlist":    shortlist,
        "all_options":  len(all_opts),
        "escalations":  escalations,
        "precedents":   precedents,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 12. PRINT OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

def show(req):
    a   = analyze(req)
    bar = "█" * (a["confidence"] // 10) + "░" * (10 - a["confidence"] // 10)

    print(f"\n{'═'*62}")
    print(f"  {a['request_id']}   [{bar}] {a['confidence']}%")
    print(f"  {a['category']}  |  Qty: {a['quantity']}  |  "
          f"Budget: {a['currency']} {a['budget'] or '?'}")
    print(f"  Countries: {a['countries']}  |  Deadline: {a['deadline']}")

    # Approval
    ap = a["approval"]
    if ap["tier"]:
        print(f"\n  APPROVAL  Tier {ap['tier']} — "
              f"{ap['quotes']} quote(s) — {ap['approver']}")

    # Preferred supplier
    pref = a["preferred"]
    if pref["name"]:
        icon = "✓" if pref["status"] == "VALID" else "✗"
        print(f"\n  PREFERRED  [{icon}] {pref['status']}: {pref['detail']}")

    # Validation issues
    if a["issues"]:
        print(f"\n  VALIDATION ISSUES")
        for v in a["issues"]:
            print(f"  [{v['severity']}] {v['field']}: {v['msg']}")

    # Supplier shortlist
    print(f"\n  SUPPLIERS  ({a['all_options']} valid, showing top {len(a['shortlist'])})")
    if a["shortlist"]:
        print(f"  {'#':<2}  {'Supplier':<24}  {'Total':>12}  "
              f"{'Score':>6}  {'Lead':>5}  {'Q':>4}  {'R':>4}  {'ESG':>4}")
        print(f"  {'─'*2}  {'─'*24}  {'─'*12}  {'─'*6}  {'─'*5}  "
              f"{'─'*4}  {'─'*4}  {'─'*4}")
        for i, s in enumerate(a["shortlist"], 1):
            flags = ""
            if s["expedited"]:    flags += " [EXP]"
            if s["is_preferred"]: flags += " [PREF]"
            if not s["capacity_ok"]: flags += " [CAP!]"
            print(f"  {i:<2}  {s['supplier_name']:<24}  "
                  f"{s['currency']} {s['total_price']:>8,.0f}  "
                  f"{s['score']:>6.1f}  "
                  f"{s['lead_time']:>4}d  "
                  f"{s['quality']:>4.0f}  "
                  f"{s['risk']:>4.0f}  "
                  f"{s['esg']:>4.0f}"
                  f"{flags}")
    else:
        print(f"  No compliant suppliers found.")

    # Escalations
    if a["escalations"]:
        print(f"\n  ESCALATIONS  ({len(a['escalations'])} triggered)")
        for e in a["escalations"]:
            print(f"  [{e['rule']}] → {e['target']}")
            print(f"         {e['trigger']}")
            print(f"         {e['detail']}")
    else:
        print(f"\n  ✓  No escalation required — automated decision is valid.")

    # Historical precedents
    if a["precedents"]:
        print(f"\n  PRECEDENTS")
        for p in a["precedents"]:
            print(f"  {p.get('award_id','')}  {p.get('supplier_name','')}  "
                  f"val={p.get('total_value','')}  "
                  f"savings={p.get('savings_pct','')}%  "
                  f"\"{p.get('decision_rationale','')[:60]}\"")

    print(f"{'═'*62}\n")


# ══════════════════════════════════════════════════════════════════════════════
# 13. ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        for r in requests[:3]:
            show(r)

    elif args[0].startswith("REQ-"):
        req = next((r for r in requests if r.get("request_id") == args[0]), None)
        show(req) if req else print(f"Not found: {args[0]}")

    elif args[0].startswith("--tag="):
        tag = args[0].split("=", 1)[1]
        tagged = [r for r in requests if tag in (r.get("scenario_tags") or [])]
        if not tagged:
            print(f"No requests found with tag '{tag}'")
        for r in tagged[:3]:
            show(r)

    elif args[0].startswith("--batch="):
        n = int(args[0].split("=", 1)[1])
        for r in requests[:n]:
            show(r)

    else:
        print("Usage:")
        print("  python engine.py                   # first 3 requests")
        print("  python engine.py REQ-000001        # one request by ID")
        print("  python engine.py --tag=restricted  # by scenario tag")
        print("  python engine.py --batch=20        # first N requests")
