// src/lib/adapter.ts
// Maps the Python backend's BackendResult → the frontend's AnalysisResult
// so all existing OutputPanel steps (1-6) continue to work unchanged.

import type {
  BackendResult,
  BackendSupplier,
  AnalysisResult,
  SupplierResult,
  PolicyRule,
  Escalation,
  AuditEntry,
} from './types';

function mapSupplier(s: BackendSupplier, idx: number): SupplierResult {
  return {
    supplier_id: s.supplier_id,
    name: s.supplier_name,
    rank: s.rank ?? idx + 1,
    status: s.policy_compliant ? 'compliant' : 'non_compliant',
    unit_price: s.unit_price ?? null,
    total_price: s.total_price_in_req_currency ?? s.total_price ?? null,
    currency: s.req_currency ?? s.pricing_currency,
    lead_time_days: s.lead_time_days ?? 0,
    expedited_lead_time_days: s.expedited_lead_time_days ?? null,
    quality_score: s.quality_score ?? 0,
    risk_score: s.risk_score ?? 0,
    esg_score: s.esg_score ?? 0,
    preferred: s.preferred ?? false,
    restricted: false,
    covers_region: s.covers_delivery_country ?? true,
    within_capacity: !s.capacity_flag,
    rationale: s.recommendation_note ?? '',
    exclusion_reason: null,
  };
}

function mapPolicies(b: BackendResult): PolicyRule[] {
  const rules: PolicyRule[] = [];
  const at = b.policy_evaluation?.approval_threshold;
  const val = b.validation;

  // Completeness
  rules.push({
    rule_id: 'POL-001',
    rule_name: 'Mandatory Information Check',
    status: (val?.completeness === 'pass' || !(val?.missing_fields?.length)) ? 'pass' : 'fail',
    description: val?.missing_fields?.length
      ? `Missing fields: ${val.missing_fields.join(', ')}`
      : 'All mandatory fields present.',
    impact: val?.missing_fields?.length ? 'Request cannot proceed.' : null,
  });

  // Approval threshold
  if (at) {
    const isHigh = (at.quotes_required ?? 1) >= 3;
    rules.push({
      rule_id: at.tier_id ?? 'AT-001',
      rule_name: 'Approval Threshold',
      status: isHigh ? 'warning' : 'pass',
      description: at.basis ?? `Effective value ${at.effective_contract_value} ${at.threshold_currency} → requires ${at.quotes_required} quotes from ${(at.approvers ?? []).join(', ')}.`,
      impact: isHigh ? `Formal sourcing process required. Approvers: ${(at.approvers ?? []).join(', ')}.` : null,
    });
  }

  // Preferred supplier
  const ps = b.policy_evaluation?.preferred_supplier;
  if (ps?.supplier) {
    rules.push({
      rule_id: 'POL-PS',
      rule_name: 'Preferred Supplier Status',
      status: ps.is_restricted ? 'fail' : 'pass',
      description: ps.policy_note ?? ps.status,
      impact: ps.is_restricted ? 'Escalation required — preferred supplier is restricted.' : null,
    });
  }

  // Category rules
  for (const cr of b.policy_evaluation?.category_rules_applied ?? []) {
    rules.push({
      rule_id: cr.rule_id,
      rule_name: cr.rule_type.replace(/_/g, ' '),
      status: 'pass',
      description: cr.rule_text,
      impact: null,
    });
  }

  return rules;
}

function mapEscalations(b: BackendResult): Escalation[] {
  return (b.escalations ?? []).map((e) => ({
    ...e,
    rule_id: e.rule ?? 'ESC',
    trigger: e.trigger ?? e.reason ?? e.rule ?? '',
    target: e.escalate_to ?? 'Procurement',
    urgency: (e.urgency === 'high' || e.urgency === 'medium' || e.urgency === 'low')
      ? e.urgency
      : 'medium',
    description: e.description ?? e.reason ?? '',
    action_required: `Escalate to ${e.escalate_to ?? 'Procurement'}.`,
    note: e.note,
    explanation: e.explanation,
  }));
}

function mapAuditLog(b: BackendResult): AuditEntry[] {
  const at = b.audit_trail;
  const ts = b.processed_at ?? new Date().toISOString();
  const entries: AuditEntry[] = [
    {
      timestamp: ts,
      layer: 'NLP EXTRACTOR',
      action: 'Language detection, field extraction, contradiction check',
      result: at?.nlp_used ? 'pass' : 'info',
      details: at?.nlp_used
        ? `Fields filled by NLP: [${(at?.nlp_fields_filled ?? []).join(', ') || 'none'}]. Translation: ${at?.nlp_translation_applied}. Contradictions: ${at?.nlp_contradictions_detected}.`
        : 'NLP layer disabled — raw structured fields used.',
    },
    {
      timestamp: ts,
      layer: 'RULE ENGINE',
      action: `Evaluated ${(at?.supplier_ids_evaluated ?? []).length} suppliers, applied ${(at?.policies_checked ?? []).length} policies`,
      result: (b.validation?.missing_fields?.length ?? 0) > 0 ? 'warning' : 'pass',
      details: `Policies: ${(at?.policies_checked ?? []).join(', ')}. Region: ${at?.pricing_region_used ?? '—'}. ${at?.pricing_tiers_applied ?? ''}`,
    },
    {
      timestamp: ts,
      layer: 'CALIBRATOR',
      action: 'Re-scored shortlist with logistic regression weights',
      result: 'pass',
      details: `CV-AUC: ${b._pipeline?.calibration_auc ?? '—'}. ESG-adjusted weights applied. Suppliers re-ranked.`,
    },
    {
      timestamp: ts,
      layer: 'RATIONALE GEN',
      action: 'Generated recommendation notes & reasoning',
      result: b._pipeline?.rationale_enabled ? 'pass' : 'info',
      details: b._pipeline?.rationale_enabled
        ? `Rationale generated for ${b.supplier_shortlist?.length ?? 0} suppliers.`
        : 'Rationale layer disabled — template fallback used.',
    },
    {
      timestamp: ts,
      layer: 'RECOMMENDER',
      action: 'Final recommendation decision',
      result: b.recommendation?.status === 'proceed' ? 'pass' : 'warning',
      details: `Status: ${b.recommendation?.status}. Top supplier: ${b.recommendation?.top_supplier ?? '—'}. Quotes required: ${b.recommendation?.quotes_required ?? 1}.`,
    },
  ];
  // FX rates note
  if (Object.keys(at?.fx_rates_used ?? {}).length > 0) {
    entries.push({
      timestamp: ts,
      layer: 'FX',
      action: 'FX rate lookup',
      result: 'info',
      details: `Rates used: ${Object.entries(at?.fx_rates_used ?? {}).map(([k, v]) => `${k}=${v}`).join(', ')}.`,
    });
  }
  return entries;
}

export function adaptBackendResult(b: BackendResult): AnalysisResult {
  const interp = b.request_interpretation ?? {};
  const rec = b.recommendation ?? {};

  const request_parsed = {
    item: interp.category_l2 ?? interp.category_l1 ?? 'Unknown',
    category_l1: interp.category_l1 ?? '',
    category_l2: interp.category_l2 ?? '',
    quantity: interp.quantity ?? null,
    unit: interp.unit_of_measure ?? '',
    budget_amount: interp.budget_amount ?? null,
    currency: interp.currency ?? 'EUR',
    deadline_iso: interp.required_by_date ?? null,
    deadline_days_from_today: interp.days_until_required ?? null,
    country: interp.delivery_country ?? (interp.delivery_countries?.[0] ?? ''),
    delivery_countries: interp.delivery_countries ?? [],
    preferred_supplier_mentioned: interp.preferred_supplier_stated ?? null,
    business_unit: null,
    data_residency: interp.data_residency_required ?? false,
    esg_required: interp.esg_requirement ?? false,
  };

  const issues: AnalysisResult['compatibility']['issues'] = [];
  for (const f of b.validation?.missing_fields ?? []) {
    issues.push({ field: f, severity: 'error', description: `Field '${f}' is missing.`, detected_value: null, expected: 'A value' });
  }
  for (const i of b.validation?.issues_detected ?? []) {
    const desc = typeof i === 'string' ? i : JSON.stringify(i);
    issues.push({ field: 'issue', severity: 'warning', description: desc, detected_value: null, expected: null });
  }

  const compatibility: AnalysisResult['compatibility'] = {
    overall_status: issues.some(i => i.severity === 'error') ? 'error' : issues.length > 0 ? 'warning' : 'ok',
    issues,
  };

  const suppliers = (b.supplier_shortlist ?? []).map(mapSupplier);
  const policy_evaluation = mapPolicies(b);
  const escalations = mapEscalations(b);
  const audit_log = mapAuditLog(b);

  // Determine decision type
  const status = rec.status ?? '';
  const decision: AnalysisResult['recommendation']['decision'] =
    status === 'proceed' ? 'auto_approve' :
    status === 'escalate' ? 'soft_escalate' : 'hard_escalate';

  const totalVal = rec.top_supplier_total ?? null;
  const quotesReq = rec.quotes_required ?? 1;

  const recommendation: AnalysisResult['recommendation'] = {
    decision,
    recommended_supplier_id: suppliers[0]?.supplier_id ?? null,
    recommended_supplier_name: rec.top_supplier ?? null,
    confidence: decision === 'auto_approve' ? 'high' : decision === 'soft_escalate' ? 'medium' : 'low',
    confidence_score: decision === 'auto_approve' ? 90 : decision === 'soft_escalate' ? 60 : 35,
    approval_tier: null,
    required_approver: (b.policy_evaluation?.approval_threshold?.approvers ?? []).join(', ') || 'Business',
    quotes_required: quotesReq,
    total_estimated_value: totalVal,
    currency: interp.currency ?? 'EUR',
    reasoning: rec.reason ?? '',
    next_steps: decision === 'auto_approve'
      ? [`Obtain quote from ${rec.top_supplier ?? 'top supplier'}`, 'Route for approval', 'Issue Purchase Order']
      : ['Review escalation requirements', 'Obtain required quotes', 'Route for human approval'],
  };

  return { request_parsed, compatibility, policy_evaluation, suppliers, escalations, recommendation, audit_log };
}
