import { AnalysisResult } from './types';

const TODAY = new Date().toISOString().split('T')[0];
const T14 = (() => { const d = new Date(); d.setDate(d.getDate() + 14); return d.toISOString().split('T')[0]; })();
const T45 = (() => { const d = new Date(); d.setDate(d.getDate() + 45); return d.toISOString().split('T')[0]; })();

export const DEMO_RESULTS: Record<string, AnalysisResult> = {
  restricted: {
    request_parsed: { item: "Business Laptops", category_l1: "IT", category_l2: "Laptops", quantity: 500, unit: "units", budget_amount: 400000, currency: "EUR", deadline_iso: T14, deadline_days_from_today: 14, country: "DE", delivery_countries: ["DE"], preferred_supplier_mentioned: "RestrictedTech SA", business_unit: "Engineering", data_residency: false, esg_required: false },
    compatibility: {
      overall_status: "error",
      issues: [
        { field: "preferred_supplier_mentioned", severity: "error", description: "RestrictedTech SA is on the global restricted supplier list due to an active data breach investigation. Engagement is not permitted without CPO exception approval.", detected_value: "RestrictedTech SA", expected: "A non-restricted supplier from the preferred or open market list" },
        { field: "deadline_vs_lead_time", severity: "warning", description: "Requested delivery in 14 days. Fastest compliant supplier (TechCore GmbH) has a standard lead time of 10 days — expedited delivery required.", detected_value: "14 days from today", expected: "Standard lead 10d / Expedited 6d for TechCore GmbH" },
        { field: "budget_vs_total", severity: "warning", description: "Budget of EUR 400,000 for 500 units = EUR 800/unit max. TechCore GmbH standard tier is EUR 1,020/unit → EUR 510,000 total — EUR 110,000 over budget.", detected_value: "EUR 400,000 budget", expected: "EUR 510,000 required at standard tier" },
      ],
    },
    policy_evaluation: [
      { rule_id: "POL-001", rule_name: "Restricted Supplier Check", status: "fail", description: "RestrictedTech SA appears in the restricted_suppliers list (GLOBAL scope). No procurement can proceed without CPO exception.", impact: "Request cannot auto-approve. Escalation to Procurement Manager required under ER-002." },
      { rule_id: "POL-002", rule_name: "Approval Threshold", status: "fail", description: "Estimated total (500 × EUR 1,020) = EUR 510,000 → Tier 4. Requires 3 quotes and Head of Strategic Sourcing approval.", impact: "Business-level approval is insufficient." },
      { rule_id: "POL-003", rule_name: "Budget vs. Market Price", status: "warning", description: "Budget EUR 400,000 is EUR 110,000 below estimated procurement cost of EUR 510,000.", impact: "Budget must be revised or scope reduced before award." },
      { rule_id: "POL-004", rule_name: "Lead Time Feasibility", status: "warning", description: "14-day deadline: expedited delivery (6d) from TechCore GmbH required. Adds ~8% premium → EUR 551,000.", impact: "Standard delivery cannot meet the deadline. Expedited surcharge applies." },
      { rule_id: "POL-005", rule_name: "Competitive Quotes Required", status: "fail", description: "Tier 4 requires 3 competitive quotes. Only 2 compliant suppliers available — exception needed.", impact: "Award cannot proceed until 3 quotes obtained or exception approved." },
    ],
    suppliers: [
      { supplier_id: "SUP-0001", name: "TechCore GmbH", rank: 1, status: "compliant", unit_price: 1020, total_price: 510000, currency: "EUR", lead_time_days: 10, expedited_lead_time_days: 6, quality_score: 88, risk_score: 12, esg_score: 72, preferred: true, restricted: false, covers_region: true, within_capacity: true, rationale: "Preferred supplier. Highest quality. Expedited delivery (6d) meets deadline. Total exceeds budget — revision required.", exclusion_reason: null },
      { supplier_id: "SUP-0002", name: "GlobalTech Solutions", rank: 2, status: "compliant", unit_price: 980, total_price: 490000, currency: "EUR", lead_time_days: 14, expedited_lead_time_days: 9, quality_score: 82, risk_score: 18, esg_score: 65, preferred: false, restricted: false, covers_region: true, within_capacity: true, rationale: "Lower unit price — total EUR 490,000. 14d lead time is exactly at deadline. Expedited 9d safer.", exclusion_reason: null },
      { supplier_id: "SUP-0003", name: "DigiPro Systems", rank: 3, status: "capacity_exceeded", unit_price: 950, total_price: 475000, currency: "EUR", lead_time_days: 15, expedited_lead_time_days: 10, quality_score: 79, risk_score: 22, esg_score: 58, preferred: false, restricted: false, covers_region: true, within_capacity: false, rationale: "Lowest price but capacity concern and 15d lead time exceeds deadline.", exclusion_reason: "Monthly capacity (1,500 units) may be insufficient. Lead time 15d exceeds deadline." },
      { supplier_id: "SUP-0004", name: "RestrictedTech SA", rank: 4, status: "restricted", unit_price: null, total_price: null, currency: "EUR", lead_time_days: 0, expedited_lead_time_days: null, quality_score: 91, risk_score: 5, esg_score: 80, preferred: false, restricted: true, covers_region: true, within_capacity: true, rationale: "Excluded from evaluation.", exclusion_reason: "GLOBAL RESTRICTION — under investigation for data breach. No engagement without CPO exception." },
    ],
    escalations: [
      { rule_id: "ER-002", trigger: "Preferred supplier (RestrictedTech SA) is globally restricted", target: "Procurement Manager", urgency: "high", description: "Requester named RestrictedTech SA as preferred. This supplier is globally restricted due to a data breach investigation.", action_required: "Notify requester. Obtain CPO exception or redirect to TechCore GmbH." },
      { rule_id: "ER-003", trigger: "Estimated contract value EUR 510,000 exceeds Tier 3 threshold", target: "Head of Strategic Sourcing", urgency: "high", description: "Total spend EUR 510,000 → Tier 4. Requires Head of Strategic Sourcing approval and 3 competitive quotes.", action_required: "Initiate Tier 4 sourcing process. Obtain 3 quotes. Route for Head of Strategic Sourcing approval." },
      { rule_id: "ER-001", trigger: "Budget insufficient for estimated market cost", target: "Requester", urgency: "medium", description: "Budget EUR 400,000 is EUR 110,000 below estimated cost.", action_required: "Request budget revision to minimum EUR 490,000 or reduce quantity." },
    ],
    recommendation: { decision: "hard_escalate", recommended_supplier_id: "SUP-0001", recommended_supplier_name: "TechCore GmbH (pending budget revision & escalation resolution)", confidence: "medium", confidence_score: 42, approval_tier: 4, required_approver: "Head of Strategic Sourcing", quotes_required: 3, total_estimated_value: 510000, currency: "EUR", reasoning: "Cannot auto-approve: preferred supplier restricted, total exceeds Tier 3, budget EUR 110K short. Subject to resolution, TechCore GmbH is recommended — preferred, highest quality (88), expedited 6d meets 14-day deadline.", next_steps: ["Procurement Manager to notify requester that RestrictedTech SA is restricted", "Requester to revise budget to minimum EUR 490,000", "Obtain 3 competitive quotes (TechCore, GlobalTech, DigiPro)", "Route for Head of Strategic Sourcing approval", "Conditional order with TechCore on expedited basis pending approvals", "Issue formal award once all approvals documented"] },
    audit_log: [
      { timestamp: TODAY + "T09:00:01Z", layer: "PARSER", action: "Extracted fields from free-text request", result: "pass", details: "item=Laptops, qty=500, budget=400000 EUR, deadline=14 days, preferred=RestrictedTech SA" },
      { timestamp: TODAY + "T09:00:02Z", layer: "VALIDATOR", action: "Validated field completeness", result: "warning", details: "3 issues: restricted supplier, budget shortfall, deadline pressure" },
      { timestamp: TODAY + "T09:00:03Z", layer: "POLICY ENGINE", action: "Checked restricted_suppliers list", result: "fail", details: "RestrictedTech SA matched GLOBAL restriction — ER-002 triggered" },
      { timestamp: TODAY + "T09:00:04Z", layer: "POLICY ENGINE", action: "Computed approval tier — EUR 510,000", result: "fail", details: "Tier 4 — Head of Strategic Sourcing + 3 quotes required" },
      { timestamp: TODAY + "T09:00:05Z", layer: "SUPPLIER SCORER", action: "Evaluated 4 suppliers in IT/Laptops EU", result: "warning", details: "1 restricted, 1 capacity concern, 2 fully compliant" },
      { timestamp: TODAY + "T09:00:06Z", layer: "SUPPLIER SCORER", action: "Applied pricing for qty=500", result: "pass", details: "TechCore EUR 1,020 × 500 = EUR 510,000 | GlobalTech EUR 980 × 500 = EUR 490,000" },
      { timestamp: TODAY + "T09:00:07Z", layer: "ESCALATION", action: "Fired ER-002, ER-003, ER-001", result: "fail", details: "3 escalations: Procurement Manager (high), Head of Sourcing (high), Requester (medium)" },
      { timestamp: TODAY + "T09:00:08Z", layer: "RECOMMENDER", action: "Generated recommendation", result: "warning", details: "decision=hard_escalate, confidence=42%, recommended=TechCore GmbH pending resolution" },
    ],
  },
  missing: {
    request_parsed: { item: "Cloud Compute Resources", category_l1: "IT", category_l2: "Cloud Compute", quantity: null, unit: "months", budget_amount: null, currency: "USD", deadline_iso: null, deadline_days_from_today: null, country: "SG", delivery_countries: ["SG"], preferred_supplier_mentioned: null, business_unit: "Technology", data_residency: true, esg_required: false },
    compatibility: {
      overall_status: "error",
      issues: [
        { field: "quantity", severity: "error", description: "No quantity provided. 'Whatever is needed' is not a valid specification. Required to determine pricing, capacity, and approval threshold.", detected_value: "null", expected: "A numeric quantity (vCPU hours, TB, license months)" },
        { field: "budget_amount", severity: "error", description: "No budget amount provided. Mandatory to determine approval tier.", detected_value: "null", expected: "A numeric budget in USD" },
        { field: "required_by_date", severity: "warning", description: "'Urgently' suggests time pressure but provides no actionable deadline.", detected_value: "urgently (no date)", expected: "A specific required-by date" },
        { field: "specification", severity: "warning", description: "'Cloud compute resources' is ambiguous — vCPU, memory, storage, and service type must be defined.", detected_value: "'whatever is needed for the project'", expected: "Specific resource type, scale, and duration" },
        { field: "data_residency_constraint", severity: "info", description: "Data residency flagged for SG. APAC data sovereignty applies — NovaByte AG (EU/CH only) is ineligible.", detected_value: "data_residency=true, country=SG", expected: "Supplier with APAC data residency capability" },
      ],
    },
    policy_evaluation: [
      { rule_id: "POL-001", rule_name: "Mandatory Information Check", status: "fail", description: "Quantity and budget_amount are null — both mandatory. Cannot evaluate suppliers, costs, or approval tier.", impact: "Request cannot proceed. ER-001 triggered immediately." },
      { rule_id: "POL-002", rule_name: "Data Residency Rule (APAC)", status: "warning", description: "SG delivery + data_residency=true → APAC data sovereignty. NovaByte AG (EU/CH only) is automatically disqualified.", impact: "Supplier pool restricted to APAC-capable providers." },
      { rule_id: "POL-003", rule_name: "Security Review (Cloud Compute)", status: "warning", description: "IT/Cloud Compute requires security review for contracts above USD 25,000. Cannot assess without budget.", impact: "Security review mandatory before award regardless of final value." },
    ],
    suppliers: [
      { supplier_id: "SUP-0005", name: "NovaByte AG", rank: 1, status: "non_compliant", unit_price: null, total_price: null, currency: "CHF", lead_time_days: 0, expedited_lead_time_days: null, quality_score: 92, risk_score: 8, esg_score: 85, preferred: true, restricted: false, covers_region: false, within_capacity: true, rationale: "Preferred supplier but does not cover APAC/SG. Data residency cannot be satisfied.", exclusion_reason: "Region mismatch: NovaByte AG serves EU/CH only. SG delivery with data residency cannot be fulfilled." },
      { supplier_id: "SUP-0006", name: "CloudFirst Inc", rank: 2, status: "compliant", unit_price: null, total_price: null, currency: "USD", lead_time_days: 0, expedited_lead_time_days: null, quality_score: 85, risk_score: 15, esg_score: 70, preferred: false, restricted: false, covers_region: true, within_capacity: true, rationale: "Covers Americas, APAC, EU — eligible for SG delivery with data residency. Cannot price without quantity.", exclusion_reason: null },
    ],
    escalations: [
      { rule_id: "ER-001", trigger: "Both budget_amount and quantity are null — mandatory fields missing", target: "Requester", urgency: "high", description: "Request cannot be processed without quantity and budget. Must provide: resource requirements, budget in USD, required-by date.", action_required: "Return to Technology business unit. Request mandatory fields before resubmission." },
      { rule_id: "ER-005", trigger: "Data residency constraint for SG — preferred supplier ineligible", target: "Security/Compliance", urgency: "medium", description: "NovaByte AG does not cover APAC. Data residency for SG must be confirmed with selected supplier.", action_required: "Verify APAC data residency with CloudFirst Inc. Obtain Security sign-off before award." },
    ],
    recommendation: { decision: "hard_escalate", recommended_supplier_id: null, recommended_supplier_name: null, confidence: "low", confidence_score: 10, approval_tier: null, required_approver: "Requester (information required)", quotes_required: 2, total_estimated_value: null, currency: "USD", reasoning: "Cannot be evaluated. Quantity and budget — minimum required inputs — are absent. 'Whatever is needed' provides no actionable specification. NovaByte AG is ineligible for SG. Must return to requester.", next_steps: ["Return request to Technology BU under ER-001", "Requester must provide resource type, quantity, budget, required-by date", "Re-run analysis — CloudFirst Inc is likely eligible for APAC", "Security/Compliance to confirm APAC data residency", "Complete mandatory security review (IT/Cloud Compute)"] },
    audit_log: [
      { timestamp: TODAY + "T10:00:01Z", layer: "PARSER", action: "Attempted field extraction from free-text", result: "warning", details: "item=Cloud Compute, country=SG, data_residency=true | qty=null, budget=null, deadline=null" },
      { timestamp: TODAY + "T10:00:02Z", layer: "VALIDATOR", action: "Validated mandatory field presence", result: "fail", details: "FAIL: quantity=null, budget_amount=null — 2 mandatory fields absent" },
      { timestamp: TODAY + "T10:00:03Z", layer: "POLICY ENGINE", action: "Checked APAC data residency rules for SG", result: "warning", details: "APAC data sovereignty applies — supplier must have SG data residency" },
      { timestamp: TODAY + "T10:00:04Z", layer: "SUPPLIER SCORER", action: "Evaluated 2 suppliers in IT/Cloud Compute", result: "warning", details: "NovaByte AG: region mismatch. CloudFirst Inc: eligible but cannot price." },
      { timestamp: TODAY + "T10:00:05Z", layer: "ESCALATION", action: "Fired ER-001 and ER-005", result: "fail", details: "ER-001 → Requester (high) | ER-005 → Security/Compliance (medium)" },
      { timestamp: TODAY + "T10:00:06Z", layer: "RECOMMENDER", action: "Generated recommendation — hard escalate", result: "fail", details: "decision=hard_escalate, confidence=10%, no award possible" },
    ],
  },
  standard: {
    request_parsed: { item: "Business Laptops", category_l1: "IT", category_l2: "Laptops", quantity: 50, unit: "units", budget_amount: 60000, currency: "EUR", deadline_iso: T45, deadline_days_from_today: 45, country: "NL", delivery_countries: ["NL"], preferred_supplier_mentioned: null, business_unit: "Finance", data_residency: false, esg_required: true },
    compatibility: { overall_status: "ok", issues: [] },
    policy_evaluation: [
      { rule_id: "POL-001", rule_name: "Mandatory Information Check", status: "pass", description: "All fields present: qty=50, budget=EUR 60,000, deadline=45d, country=NL.", impact: null },
      { rule_id: "POL-002", rule_name: "Approval Threshold", status: "pass", description: "Estimated total (50 × EUR 1,100) = EUR 55,000 → Tier 2. Requires 2 quotes, Business + Procurement approval.", impact: null },
      { rule_id: "POL-003", rule_name: "Budget vs. Market Price", status: "pass", description: "Budget EUR 60,000 covers estimated EUR 55,000 with EUR 5,000 contingency (8.3%).", impact: null },
      { rule_id: "POL-004", rule_name: "Lead Time Feasibility", status: "pass", description: "45-day deadline exceeds 12-day standard lead time for TechCore GmbH.", impact: null },
      { rule_id: "POL-005", rule_name: "ESG Requirement", status: "pass", description: "ESG flagged. TechCore GmbH score: 72/100 — acceptable.", impact: null },
    ],
    suppliers: [
      { supplier_id: "SUP-0001", name: "TechCore GmbH", rank: 1, status: "compliant", unit_price: 1100, total_price: 55000, currency: "EUR", lead_time_days: 12, expedited_lead_time_days: 7, quality_score: 88, risk_score: 12, esg_score: 72, preferred: true, restricted: false, covers_region: true, within_capacity: true, rationale: "Preferred EU supplier. Quality 88, ESG 72, Risk 12. EUR 55,000 within budget. 12d lead well within 45d deadline.", exclusion_reason: null },
      { supplier_id: "SUP-0002", name: "GlobalTech Solutions", rank: 2, status: "compliant", unit_price: 1050, total_price: 52500, currency: "EUR", lead_time_days: 16, expedited_lead_time_days: 10, quality_score: 82, risk_score: 18, esg_score: 65, preferred: false, restricted: false, covers_region: true, within_capacity: true, rationale: "EUR 2,500 cheaper but lower quality (82) and ESG (65). 16d lead still within deadline. Good second quote.", exclusion_reason: null },
      { supplier_id: "SUP-0003", name: "DigiPro Systems", rank: 3, status: "compliant", unit_price: 1020, total_price: 51000, currency: "EUR", lead_time_days: 18, expedited_lead_time_days: 12, quality_score: 79, risk_score: 22, esg_score: 58, preferred: false, restricted: false, covers_region: true, within_capacity: true, rationale: "Lowest price (EUR 51,000). Weakest quality (79) and ESG (58). 18d lead acceptable. Good third comparison.", exclusion_reason: null },
      { supplier_id: "SUP-0004", name: "RestrictedTech SA", rank: 4, status: "restricted", unit_price: null, total_price: null, currency: "EUR", lead_time_days: 0, expedited_lead_time_days: null, quality_score: 91, risk_score: 5, esg_score: 80, preferred: false, restricted: true, covers_region: true, within_capacity: true, rationale: "Excluded.", exclusion_reason: "GLOBAL RESTRICTION — data breach investigation. Not eligible." },
    ],
    escalations: [],
    recommendation: { decision: "auto_approve", recommended_supplier_id: "SUP-0001", recommended_supplier_name: "TechCore GmbH", confidence: "high", confidence_score: 91, approval_tier: 2, required_approver: "Business + Procurement", quotes_required: 2, total_estimated_value: 55000, currency: "EUR", reasoning: "Well-formed standard request, no violations. TechCore GmbH: preferred EU supplier, quality 88, ESG 72, EUR 55,000 under EUR 60,000 budget, 12d delivery within 45d deadline. Tier 2 requires Business + Procurement approval and 2 quotes.", next_steps: ["Obtain formal quote from TechCore GmbH (EUR 55,000, 50 units, 12d delivery)", "Obtain second quote from GlobalTech Solutions (EUR 52,500)", "Route for Business + Procurement approval (Tier 2)", "Issue Purchase Order to TechCore GmbH upon approval", "Confirm delivery with Finance team in Amsterdam"] },
    audit_log: [
      { timestamp: TODAY + "T11:00:01Z", layer: "PARSER", action: "Extracted fields from request", result: "pass", details: "item=Laptops, qty=50, budget=60000 EUR, deadline=45d, esg=true, country=NL" },
      { timestamp: TODAY + "T11:00:02Z", layer: "VALIDATOR", action: "Validated completeness and consistency", result: "pass", details: "All mandatory fields present. No contradictions." },
      { timestamp: TODAY + "T11:00:03Z", layer: "POLICY ENGINE", action: "Checked restricted suppliers — no match", result: "pass", details: "No preferred supplier named. Restricted list: no violations." },
      { timestamp: TODAY + "T11:00:04Z", layer: "POLICY ENGINE", action: "Computed approval tier — EUR 55,000", result: "pass", details: "Tier 2 — Business + Procurement approval, 2 quotes" },
      { timestamp: TODAY + "T11:00:05Z", layer: "SUPPLIER SCORER", action: "Evaluated 4 suppliers IT/Laptops NL", result: "pass", details: "3 compliant (ranked), 1 restricted (excluded)" },
      { timestamp: TODAY + "T11:00:06Z", layer: "SUPPLIER SCORER", action: "Applied pricing tier qty=50 (100-499 band)", result: "pass", details: "TechCore EUR 1,100 × 50 = EUR 55,000 | GlobalTech EUR 1,050 × 50 = EUR 52,500" },
      { timestamp: TODAY + "T11:00:07Z", layer: "ESCALATION", action: "Evaluated escalation rules — no triggers", result: "pass", details: "All checks passed. No escalation required." },
      { timestamp: TODAY + "T11:00:08Z", layer: "RECOMMENDER", action: "Generated recommendation", result: "pass", details: "decision=auto_approve, supplier=TechCore GmbH, confidence=91%" },
    ],
  },
};

export const EXAMPLE_REQUESTS = {
  restricted: {
    text: 'We urgently need 500 business laptops for our new engineering team in Germany. The team starts in 2 weeks and cannot work without equipment. We worked with RestrictedTech SA before and the quality was excellent — please use them again. Budget is 400,000 EUR.',
    cat1: 'IT', cat2: 'Laptops', qty: '500', unit: 'units',
    date: T14, budget: '400000', currency: 'EUR', country: 'DE',
    supplier: 'RestrictedTech SA', bu: 'Engineering', delivery: 'DE',
    esg: false, drc: false, channel: 'portal', lang: 'en',
  },
  missing: {
    text: 'We need some cloud compute resources for our Singapore office. We are migrating our data platform and need resources urgently. Please set up whatever is needed for the project.',
    cat1: 'IT', cat2: 'Cloud Compute', qty: '', unit: 'months',
    date: '', budget: '', currency: 'USD', country: 'SG',
    supplier: '', bu: 'Technology', delivery: 'SG',
    esg: false, drc: true, channel: 'email', lang: 'en',
  },
  standard: {
    text: 'Please procure 50 laptops for the new Amsterdam finance team. Standard business spec is fine. Delivery needed by end of next month. Budget is 60,000 EUR. No preference on supplier but ESG credentials matter.',
    cat1: 'IT', cat2: 'Laptops', qty: '50', unit: 'units',
    date: T45, budget: '60000', currency: 'EUR', country: 'NL',
    supplier: '', bu: 'Finance', delivery: 'NL',
    esg: true, drc: false, channel: 'portal', lang: 'en',
  },
};
