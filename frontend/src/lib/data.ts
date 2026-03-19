import {
  Supplier,
  PricingTier,
  Policies,
  AnalysisResult,
  PurchaseRequest,
  SupplierResult,
  PolicyRule,
  Escalation,
  AuditEntry,
} from './types';

// ── Supplier Database ──
export const SUPPLIERS: Supplier[] = [
  { id: "SUP-0001", name: "TechCore GmbH", cat1: "IT", cat2: "Laptops", regions: ["EU"], currency: "EUR", quality: 88, risk: 12, esg: 72, preferred: true, restricted: false, restriction_reason: null, capacity: 2000 },
  { id: "SUP-0002", name: "GlobalTech Solutions", cat1: "IT", cat2: "Laptops", regions: ["Americas", "EU"], currency: "EUR", quality: 82, risk: 18, esg: 65, preferred: false, restricted: false, restriction_reason: null, capacity: 3000 },
  { id: "SUP-0003", name: "DigiPro Systems", cat1: "IT", cat2: "Laptops", regions: ["APAC", "EU"], currency: "EUR", quality: 79, risk: 22, esg: 58, preferred: false, restricted: false, restriction_reason: null, capacity: 1500 },
  { id: "SUP-0004", name: "RestrictedTech SA", cat1: "IT", cat2: "Laptops", regions: ["EU"], currency: "EUR", quality: 91, risk: 5, esg: 80, preferred: false, restricted: true, restriction_reason: "Under investigation for data breach. GLOBAL RESTRICTION — CPO exception required.", capacity: 4000 },
  { id: "SUP-0005", name: "NovaByte AG", cat1: "IT", cat2: "Cloud Compute", regions: ["EU", "CH"], currency: "CHF", quality: 92, risk: 8, esg: 85, preferred: true, restricted: false, restriction_reason: null, capacity: 9999 },
  { id: "SUP-0006", name: "CloudFirst Inc", cat1: "IT", cat2: "Cloud Compute", regions: ["Americas", "APAC", "EU"], currency: "USD", quality: 85, risk: 15, esg: 70, preferred: false, restricted: false, restriction_reason: null, capacity: 9999 },
  { id: "SUP-0007", name: "FacilityPro GmbH", cat1: "Facilities", cat2: "Office Supplies", regions: ["EU"], currency: "EUR", quality: 80, risk: 20, esg: 68, preferred: true, restricted: false, restriction_reason: null, capacity: 5000 },
  { id: "SUP-0009", name: "ConsultaCorp", cat1: "Professional Services", cat2: "Data Engineering Services", regions: ["EU"], currency: "EUR", quality: 87, risk: 14, esg: 73, preferred: true, restricted: false, restriction_reason: null, capacity: 50 },
  { id: "SUP-0010", name: "DataMinds AG", cat1: "Professional Services", cat2: "Data Engineering Services", regions: ["EU"], currency: "EUR", quality: 83, risk: 17, esg: 69, preferred: false, restricted: false, restriction_reason: null, capacity: 40 },
  { id: "SUP-0011", name: "BrandStar Ltd", cat1: "Marketing", cat2: "Digital Marketing", regions: ["EU"], currency: "EUR", quality: 78, risk: 28, esg: 60, preferred: false, restricted: true, restriction_reason: "Brand safety review pending under ER-007.", capacity: 9999 },
  { id: "SUP-0012", name: "MediaCore GmbH", cat1: "Marketing", cat2: "Digital Marketing", regions: ["EU"], currency: "EUR", quality: 75, risk: 22, esg: 62, preferred: false, restricted: false, restriction_reason: null, capacity: 9999 },
];

// ── Pricing Tiers by Supplier ──
export const PRICING: Record<string, PricingTier[]> = {
  "SUP-0001": [
    { min: 1, max: 99, unit: 1250, lead: 14, exp: 8, exp_unit: 1350 },
    { min: 100, max: 499, unit: 1100, lead: 12, exp: 7, exp_unit: 1188 },
    { min: 500, max: 1999, unit: 1020, lead: 10, exp: 6, exp_unit: 1102 },
    { min: 2000, max: 99999, unit: 920, lead: 8, exp: 5, exp_unit: 994 },
  ],
  "SUP-0002": [
    { min: 1, max: 99, unit: 1180, lead: 18, exp: 12, exp_unit: 1274 },
    { min: 100, max: 499, unit: 1050, lead: 16, exp: 10, exp_unit: 1134 },
    { min: 500, max: 1999, unit: 980, lead: 14, exp: 9, exp_unit: 1058 },
    { min: 2000, max: 99999, unit: 890, lead: 12, exp: 8, exp_unit: 961 },
  ],
  "SUP-0003": [
    { min: 1, max: 99, unit: 1150, lead: 21, exp: 14, exp_unit: 1242 },
    { min: 100, max: 499, unit: 1020, lead: 18, exp: 12, exp_unit: 1102 },
    { min: 500, max: 1999, unit: 950, lead: 15, exp: 10, exp_unit: 1026 },
    { min: 2000, max: 99999, unit: 860, lead: 12, exp: 8, exp_unit: 929 },
  ],
};

// ── Approval Policies ──
export const POLICIES: Policies = {
  approval: {
    EUR: [
      { tier: 1, max: 25000, quotes: 1, approver: "Business" },
      { tier: 2, min: 25000, max: 100000, quotes: 2, approver: "Business + Procurement" },
      { tier: 3, min: 100000, max: 500000, quotes: 3, approver: "Head of Category" },
      { tier: 4, min: 500000, max: 5000000, quotes: 3, approver: "Head of Strategic Sourcing" },
      { tier: 5, min: 5000000, max: 1e12, quotes: 3, approver: "CPO" },
    ],
    CHF: [
      { tier: 1, max: 27500, quotes: 1, approver: "Business" },
      { tier: 2, min: 27500, max: 110000, quotes: 2, approver: "Business + Procurement" },
      { tier: 3, min: 110000, max: 550000, quotes: 3, approver: "Head of Category" },
      { tier: 4, min: 550000, max: 5500000, quotes: 3, approver: "Head of Strategic Sourcing" },
      { tier: 5, min: 5500000, max: 1e12, quotes: 3, approver: "CPO" },
    ],
    USD: [
      { tier: 1, max: 27000, quotes: 1, approver: "Business" },
      { tier: 2, min: 27000, max: 108000, quotes: 2, approver: "Business + Procurement" },
      { tier: 3, min: 108000, max: 540000, quotes: 3, approver: "Head of Category" },
      { tier: 4, min: 540000, max: 5400000, quotes: 3, approver: "Head of Strategic Sourcing" },
      { tier: 5, min: 5400000, max: 1e12, quotes: 3, approver: "CPO" },
    ],
  },
  escalation: [
    { id: "ER-001", trigger: "Missing required information", target: "Requester" },
    { id: "ER-002", trigger: "Preferred supplier is restricted", target: "Procurement Manager" },
    { id: "ER-003", trigger: "Contract value exceeds tier 3", target: "Head of Strategic Sourcing" },
    { id: "ER-004", trigger: "No compliant supplier identified", target: "Head of Category" },
    { id: "ER-005", trigger: "Data residency cannot be satisfied", target: "Security/Compliance" },
    { id: "ER-006", trigger: "Quantity exceeds supplier capacity", target: "Sourcing Excellence Lead" },
    { id: "ER-007", trigger: "Brand safety concern in Marketing", target: "Marketing Governance Lead" },
    { id: "ER-008", trigger: "Supplier not screened in delivery country", target: "Regional Compliance Lead" },
  ],
};

// ── Cat2 Taxonomy ──
export const CAT2: Record<string, string[]> = {
  IT: ['Laptops', 'Cloud Compute', 'Software Licences', 'Hardware', 'Networking'],
  Facilities: ['Office Supplies', 'Cleaning Services', 'Security', 'HVAC', 'Furniture'],
  'Professional Services': ['Data Engineering Services', 'Consulting', 'Legal', 'HR Services', 'Training'],
  Marketing: ['Digital Marketing', 'Events', 'Print & Design', 'PR Services', 'Market Research'],
};

// ── Local Analysis Engine ──
function getToday(): string {
  return new Date().toISOString().split('T')[0];
}

function getDaysDiff(dateStr: string): number {
  const target = new Date(dateStr);
  const today = new Date();
  return Math.round((target.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
}

function getPricingTier(supplierId: string, qty: number): PricingTier | null {
  const tiers = PRICING[supplierId];
  if (!tiers) return null;
  return tiers.find(t => qty >= t.min && qty <= t.max) || null;
}

function getApprovalTier(currency: string, amount: number): { tier: number; quotes: number; approver: string } {
  const tiers = POLICIES.approval[currency] || POLICIES.approval['EUR'];
  for (const t of tiers) {
    if (amount < (t.max || Infinity) && amount >= (t.min || 0)) {
      return { tier: t.tier, quotes: t.quotes, approver: t.approver };
    }
  }
  return { tier: 5, quotes: 3, approver: "CPO" };
}

function supportsRegion(supplier: Supplier, country: string): boolean {
  const regionMap: Record<string, string[]> = {
    EU: ['DE', 'FR', 'NL', 'BE', 'AT', 'IT', 'ES', 'PL', 'UK', 'CH'],
    Americas: ['US', 'CA', 'BR', 'MX'],
    APAC: ['SG', 'AU', 'IN', 'JP'],
    CH: ['CH'],
  };
  return supplier.regions.some(r => {
    if (r === country) return true;
    return (regionMap[r] || []).includes(country);
  });
}

export function analyzeRequest(req: PurchaseRequest): AnalysisResult {
  const today = getToday();
  const qty = req.quantity ? Number(req.quantity) : null;
  const budget = req.budget_amount ? Number(req.budget_amount) : null;
  const deadlineDays = req.required_by_date ? getDaysDiff(req.required_by_date) : null;
  const currency = req.currency || 'EUR';
  const country = req.country || '';

  // Step 1: Parse
  const request_parsed = {
    item: req.category_l2 || req.category_l1 || 'Unknown',
    category_l1: req.category_l1,
    category_l2: req.category_l2,
    quantity: qty,
    unit: req.unit_of_measure,
    budget_amount: budget,
    currency,
    deadline_iso: req.required_by_date || null,
    deadline_days_from_today: deadlineDays,
    country,
    delivery_countries: req.delivery_countries,
    preferred_supplier_mentioned: req.preferred_supplier_mentioned || null,
    business_unit: req.business_unit || null,
    data_residency: req.data_residency_constraint,
    esg_required: req.esg_requirement,
  };

  // Step 2: Compatibility
  const issues: AnalysisResult['compatibility']['issues'] = [];

  // Check restricted preferred supplier
  const preferredName = req.preferred_supplier_mentioned?.trim();
  const restrictedPreferred = preferredName
    ? SUPPLIERS.find(s => s.restricted && s.name.toLowerCase().includes(preferredName.toLowerCase()))
    : null;

  if (restrictedPreferred) {
    issues.push({
      field: 'preferred_supplier_mentioned',
      severity: 'error',
      description: `${restrictedPreferred.name} is on the global restricted supplier list. ${restrictedPreferred.restriction_reason}`,
      detected_value: restrictedPreferred.name,
      expected: 'A non-restricted supplier from the preferred or open market list',
    });
  }

  if (!qty) {
    issues.push({ field: 'quantity', severity: 'error', description: 'No quantity provided. Quantity is required to determine pricing tier, supplier capacity, and approval threshold.', detected_value: 'null', expected: 'A numeric quantity' });
  }
  if (!budget) {
    issues.push({ field: 'budget_amount', severity: 'error', description: 'No budget amount provided. Budget is mandatory to determine approval tier.', detected_value: 'null', expected: 'A numeric budget amount' });
  }
  if (!req.required_by_date) {
    issues.push({ field: 'required_by_date', severity: 'warning', description: 'No delivery date specified.', detected_value: 'null', expected: 'A specific required-by date' });
  }

  const compatibility: AnalysisResult['compatibility'] = {
    overall_status: issues.some(i => i.severity === 'error') ? 'error' : issues.some(i => i.severity === 'warning') ? 'warning' : 'ok',
    issues,
  };

  // Step 3: Supplier evaluation
  const candidateSuppliers = SUPPLIERS.filter(
    s => (!req.category_l1 || s.cat1 === req.category_l1) && (!req.category_l2 || s.cat2 === req.category_l2)
  );

  let estimatedValue: number | null = null;
  const supplierResults: SupplierResult[] = candidateSuppliers.map((s, idx) => {
    const isRestricted = s.restricted;
    const coversRegion = !country || supportsRegion(s, country);
    const pricingTier = qty ? getPricingTier(s.id, qty) : null;
    const unitPrice = pricingTier ? pricingTier.unit : null;
    const totalPrice = unitPrice && qty ? unitPrice * qty : null;
    const withinCapacity = qty ? qty <= s.capacity : true;

    if (idx === 0 && totalPrice) estimatedValue = totalPrice;

    let status: SupplierResult['status'] = 'compliant';
    let exclusionReason: string | null = null;
    if (isRestricted) { status = 'restricted'; exclusionReason = s.restriction_reason || 'Supplier is restricted.'; }
    else if (!coversRegion) { status = 'non_compliant'; exclusionReason = `Region mismatch: ${s.name} does not cover ${country}.`; }
    else if (!withinCapacity) { status = 'capacity_exceeded'; exclusionReason = `Monthly capacity (${s.capacity.toLocaleString()} units) insufficient for order quantity.`; }

    let rank = idx + 1;
    let rationale = isRestricted ? 'Excluded from evaluation.' : coversRegion
      ? `${s.preferred ? 'Preferred supplier. ' : ''}Quality ${s.quality}, ESG ${s.esg}, Risk ${s.risk}.${totalPrice ? ` Total: ${totalPrice.toLocaleString()} ${s.currency}.` : ''}`
      : `Does not cover the requested region.`;

    return {
      supplier_id: s.id,
      name: s.name,
      rank,
      status,
      unit_price: isRestricted ? null : unitPrice,
      total_price: isRestricted ? null : totalPrice,
      currency: s.currency,
      lead_time_days: pricingTier ? pricingTier.lead : 0,
      expedited_lead_time_days: pricingTier ? pricingTier.exp : null,
      quality_score: s.quality,
      risk_score: s.risk,
      esg_score: s.esg,
      preferred: s.preferred,
      restricted: isRestricted,
      covers_region: coversRegion,
      within_capacity: withinCapacity,
      rationale,
      exclusion_reason: exclusionReason,
    };
  });

  // Re-rank compliant suppliers first
  const compliant = supplierResults.filter(s => s.status === 'compliant');
  const nonCompliant = supplierResults.filter(s => s.status !== 'compliant');
  let rank = 1;
  compliant.forEach(s => { s.rank = rank++; });
  nonCompliant.forEach(s => { s.rank = rank++; });
  const suppliers = [...compliant, ...nonCompliant];

  // Step 4: Policy evaluation
  const estVal = estimatedValue as unknown as number | null;
  const approvalInfo = estVal ? getApprovalTier(currency, estVal) : null;
  const policies: PolicyRule[] = [];

  // Mandatory info check
  const missingMandatory = !qty || !budget;
  policies.push({
    rule_id: 'POL-001', rule_name: 'Mandatory Information Check',
    status: missingMandatory ? 'fail' : 'pass',
    description: missingMandatory ? 'Missing required fields: quantity and/or budget amount.' : 'All mandatory fields present.',
    impact: missingMandatory ? 'Request cannot proceed without required information.' : null,
  });

  // Restricted supplier
  if (restrictedPreferred) {
    policies.push({
      rule_id: 'POL-002', rule_name: 'Restricted Supplier Check', status: 'fail',
      description: `${restrictedPreferred.name} is globally restricted. ${restrictedPreferred.restriction_reason}`,
      impact: 'Escalation to Procurement Manager required under ER-002.',
    });
  }

  // Approval tier
  if (approvalInfo && estVal) {
    policies.push({
      rule_id: 'POL-003', rule_name: 'Approval Threshold', status: approvalInfo.tier >= 3 ? 'fail' : 'pass',
      description: `Estimated total ${currency} ${estVal.toLocaleString()} → Tier ${approvalInfo.tier}. Requires ${approvalInfo.quotes} quotes, approver: ${approvalInfo.approver}.`,
      impact: approvalInfo.tier >= 3 ? `Tier ${approvalInfo.tier} spend requires formal sourcing process.` : null,
    });
  }

  // Budget vs market
  if (budget && estVal) {
    const budgetOk = budget >= estVal;
    policies.push({
      rule_id: 'POL-004', rule_name: 'Budget vs. Market Price',
      status: budgetOk ? 'pass' : 'warning',
      description: budgetOk
        ? `Budget ${currency} ${budget.toLocaleString()} covers estimated cost of ${currency} ${estVal.toLocaleString()}.`
        : `Budget of ${currency} ${budget.toLocaleString()} is ${currency} ${(estVal - budget).toLocaleString()} below estimated procurement cost.`,
      impact: budgetOk ? null : 'Budget must be revised or scope reduced.',
    });
  }

  // ESG
  if (req.esg_requirement) {
    const topSupplier = suppliers[0];
    policies.push({
      rule_id: 'POL-005', rule_name: 'ESG Requirement',
      status: topSupplier && topSupplier.esg_score >= 60 ? 'pass' : 'warning',
      description: `ESG requirement flagged. Top supplier ESG score: ${topSupplier?.esg_score || 'N/A'}/100.`,
      impact: null,
    });
  }

  // Step 5: Escalations
  const escalations: Escalation[] = [];

  if (missingMandatory) {
    escalations.push({
      rule_id: 'ER-001', trigger: 'Missing mandatory fields (quantity and/or budget)',
      target: 'Requester', urgency: 'high',
      description: 'Request cannot be processed without quantity and budget amount.',
      action_required: 'Return request. Request completion of mandatory fields before resubmission.',
    });
  }

  if (restrictedPreferred) {
    escalations.push({
      rule_id: 'ER-002', trigger: `Preferred supplier (${restrictedPreferred.name}) is globally restricted`,
      target: 'Procurement Manager', urgency: 'high',
      description: `Requester named ${restrictedPreferred.name} which is globally restricted.`,
      action_required: 'Notify requester. Redirect to compliant alternatives or escalate for CPO exception.',
    });
  }

  if (approvalInfo && approvalInfo.tier >= 4 && estVal) {
    escalations.push({
      rule_id: 'ER-003', trigger: `Estimated value ${currency} ${estVal.toLocaleString()} exceeds Tier 3`,
      target: 'Head of Strategic Sourcing', urgency: 'high',
      description: `Total spend crosses into Tier ${approvalInfo.tier}, requiring ${approvalInfo.quotes} quotes.`,
      action_required: `Initiate Tier ${approvalInfo.tier} sourcing process and route for ${approvalInfo.approver} approval.`,
    });
  }

  if (req.data_residency_constraint) {
    escalations.push({
      rule_id: 'ER-005', trigger: 'Data residency constraint active',
      target: 'Security/Compliance', urgency: 'medium',
      description: 'Data residency flag requires supplier verification for regional data sovereignty.',
      action_required: 'Verify data residency capability with shortlisted supplier. Obtain Security sign-off before award.',
    });
  }

  // Step 6: Recommendation
  const compliantSuppliers = suppliers.filter(s => s.status === 'compliant');
  const hasBlockers = !!restrictedPreferred || missingMandatory;
  const needsEscalation = escalations.filter(e => e.urgency === 'high').length > 0;
  const decision: AnalysisResult['recommendation']['decision'] = hasBlockers
    ? 'hard_escalate'
    : needsEscalation
    ? 'soft_escalate'
    : 'auto_approve';

  const topCompliant = compliantSuppliers[0] || null;
  const confidenceScore = decision === 'auto_approve' ? 85 + (topCompliant?.quality_score || 0) / 10 : hasBlockers ? 35 : 60;

  // Step 7: Audit log
  const audit_log: AuditEntry[] = [
    { timestamp: today + 'T09:00:01Z', layer: 'PARSER', action: 'Extracted structured fields from request', result: 'pass', details: `item=${request_parsed.item}, qty=${qty}, budget=${budget} ${currency}, country=${country}` },
    { timestamp: today + 'T09:00:02Z', layer: 'VALIDATOR', action: 'Validated field completeness and consistency', result: compatibility.overall_status === 'ok' ? 'pass' : 'warning', details: `${issues.length} issue(s) detected` },
    { timestamp: today + 'T09:00:03Z', layer: 'POLICY ENGINE', action: 'Evaluated procurement policies', result: policies.some(p => p.status === 'fail') ? 'fail' : 'pass', details: `${policies.filter(p => p.status === 'fail').length} violation(s), ${policies.filter(p => p.status === 'pass').length} passed` },
    { timestamp: today + 'T09:00:04Z', layer: 'SUPPLIER SCORER', action: `Evaluated ${candidateSuppliers.length} suppliers in ${req.category_l1}/${req.category_l2}`, result: compliantSuppliers.length > 0 ? 'pass' : 'fail', details: `${compliantSuppliers.length} compliant, ${candidateSuppliers.length - compliantSuppliers.length} excluded` },
    { timestamp: today + 'T09:00:05Z', layer: 'ESCALATION', action: 'Evaluated escalation rules', result: escalations.length > 0 ? 'fail' : 'pass', details: `${escalations.length} escalation(s) triggered` },
    { timestamp: today + 'T09:00:06Z', layer: 'RECOMMENDER', action: 'Generated recommendation', result: decision === 'auto_approve' ? 'pass' : 'warning', details: `decision=${decision}, confidence=${Math.round(Math.min(confidenceScore, 95))}%` },
  ];

  const recommendation: AnalysisResult['recommendation'] = {
    decision,
    recommended_supplier_id: topCompliant?.supplier_id || null,
    recommended_supplier_name: topCompliant?.name || null,
    confidence: confidenceScore >= 80 ? 'high' : confidenceScore >= 55 ? 'medium' : 'low',
    confidence_score: Math.round(Math.min(confidenceScore, 95)),
    approval_tier: approvalInfo?.tier || null,
    required_approver: approvalInfo?.approver || (missingMandatory ? 'Requester (information required)' : 'Business'),
    quotes_required: approvalInfo?.quotes || 1,
    total_estimated_value: estVal,
    currency,
    reasoning: decision === 'auto_approve'
      ? `Well-formed request with no violations. ${topCompliant?.name} is the recommended supplier with quality score ${topCompliant?.quality_score} and total estimated value ${currency} ${estVal?.toLocaleString()}.`
      : hasBlockers
      ? `Request cannot be auto-approved due to active blockers: ${escalations.map(e => e.rule_id).join(', ')}.`
      : `Request requires escalation review before approval can proceed.`,
    next_steps: decision === 'auto_approve'
      ? [`Obtain formal quote from ${topCompliant?.name}`, 'Route for approval', 'Issue Purchase Order upon approval']
      : hasBlockers
      ? ['Resolve all blockers listed in escalations', 'Resubmit once information is complete', 'Route through appropriate approval chain']
      : ['Review escalation requirements', 'Obtain required quotes', 'Route for approval'],
  };

  return { request_parsed, compatibility, policy_evaluation: policies, suppliers, escalations, recommendation, audit_log };
}
