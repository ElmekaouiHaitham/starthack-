// ── Core data types for ARIA procurement intelligence system ──

export interface Supplier {
  id: string;
  name: string;
  cat1: string;
  cat2: string;
  regions: string[];
  currency: string;
  quality: number;
  risk: number;
  esg: number;
  preferred: boolean;
  restricted: boolean;
  restriction_reason: string | null;
  capacity: number;
}

export interface PricingTier {
  min: number;
  max: number;
  unit: number;
  lead: number;
  exp: number;
  exp_unit: number;
}

export interface ApprovalTier {
  tier: number;
  max?: number;
  min?: number;
  quotes: number;
  approver: string;
}

export interface EscalationRule {
  id: string;
  trigger: string;
  target: string;
}

export interface Policies {
  approval: Record<string, ApprovalTier[]>;
  escalation: EscalationRule[];
}

// ── Analysis output types ──

export interface ParsedRequest {
  item: string;
  category_l1: string;
  category_l2: string;
  quantity: number | null;
  unit: string;
  budget_amount: number | null;
  currency: string;
  deadline_iso: string | null;
  deadline_days_from_today: number | null;
  country: string;
  delivery_countries: string[];
  preferred_supplier_mentioned: string | null;
  business_unit: string | null;
  data_residency: boolean;
  esg_required: boolean;
}

export interface CompatibilityIssue {
  field: string;
  severity: 'error' | 'warning' | 'info';
  description: string;
  detected_value: string | null;
  expected: string | null;
}

export interface Compatibility {
  overall_status: 'ok' | 'warning' | 'error';
  issues: CompatibilityIssue[];
}

export interface PolicyRule {
  rule_id: string;
  rule_name: string;
  status: 'pass' | 'fail' | 'warning';
  description: string;
  impact: string | null;
}

export interface SupplierResult {
  supplier_id: string;
  name: string;
  rank: number;
  status: 'compliant' | 'restricted' | 'non_compliant' | 'capacity_exceeded';
  unit_price: number | null;
  total_price: number | null;
  currency: string;
  lead_time_days: number;
  expedited_lead_time_days: number | null;
  quality_score: number;
  risk_score: number;
  esg_score: number;
  preferred: boolean;
  restricted: boolean;
  covers_region: boolean;
  within_capacity: boolean;
  rationale: string;
  exclusion_reason: string | null;
}

export interface Escalation {
  rule_id: string;
  trigger: string;
  target: string;
  urgency: 'high' | 'medium' | 'low';
  description: string;
  action_required: string;
  note?: string;
  explanation?: string;
  [key: string]: any;
}

export interface Recommendation {
  decision: 'auto_approve' | 'soft_escalate' | 'hard_escalate';
  recommended_supplier_id: string | null;
  recommended_supplier_name: string | null;
  confidence: 'high' | 'medium' | 'low';
  confidence_score: number;
  approval_tier: number | null;
  required_approver: string;
  quotes_required: number;
  total_estimated_value: number | null;
  currency: string;
  reasoning: string;
  next_steps: string[];
}

export interface NegotiationLever {
  type: string;
  description: string;
  parameter_change: Record<string, any>;
  saving_amount: number;
  saving_pct: number;
  new_supplier: string | null;
  original_supplier: string | null;
  confidence: 'HIGH' | 'MEDIUM' | 'LOW';
  detail: string;
}

export interface BundleOpportunity {
  opportunity_id: string;
  category_l1: string;
  category_l2: string;
  region: string;
  request_ids: string[];
  request_count: number;
  individual_quantities: number[];
  combined_quantity: number;
  individual_total_cost_eur: number;
  bundled_unit_price_eur: number;
  bundled_total_cost_eur: number;
  saving_eur: number;
  saving_pct: number;
  individual_tier_label: string;
  bundled_tier_label: string;
  tier_boundary_crossed: number;
  recommended_supplier_id: string;
  recommended_supplier_name: string;
  split_detection_flag: boolean;
  split_detail: string;
  summary: string;
}

export interface AuditEntry {
  timestamp: string;
  layer: string;
  action: string;
  result: 'pass' | 'fail' | 'warning' | 'info';
  details: string;
}

export interface AnalysisResult {
  request_parsed: ParsedRequest;
  compatibility: Compatibility;
  policy_evaluation: PolicyRule[];
  suppliers: SupplierResult[];
  escalations: Escalation[];
  recommendation: Recommendation;
  audit_log: AuditEntry[];
  negotiation_levers?: NegotiationLever[];
  bundle_opportunities?: BundleOpportunity[];
  agentic_insights?: AgenticInsight[];
  escalation_cycle_insights?: EscalationCycleInsights;
}

// ── Request input type ──
export interface PurchaseRequest {
  request_text: string;
  category_l1: string;
  category_l2: string;
  quantity: string | null;
  unit_of_measure: string;
  required_by_date: string | null;
  budget_amount: string | null;
  currency: string;
  country: string;
  preferred_supplier_mentioned: string | null;
  business_unit: string | null;
  delivery_countries: string[];
  esg_requirement: boolean;
  data_residency_constraint: boolean;
  request_channel: string;
  request_language: string;
  _enable_optimization?: boolean;
  _enable_bundling?: boolean;
  agentic_mode?: boolean;
}

// ── Backend (Python pipeline) result types ──

export interface NLPFilledField {
  original_field_value: unknown;
  nlp_value: unknown;
  unit: string | null;
  source: string;
  note: string;
}

export interface BackendRequestInterpretation {
  category_l1: string;
  category_l2: string;
  quantity: number | null;
  unit_of_measure: string;
  budget_amount: number | null;
  currency: string;
  delivery_country: string | null;
  delivery_countries: string[];
  delivery_region: string | null;
  origin_country: string | null;
  required_by_date: string | null;
  days_until_required: number | null;
  data_residency_required: boolean;
  esg_requirement: boolean;
  preferred_supplier_stated: string | null;
  incumbent_supplier: string | null;
  expedited_delivery_required: boolean;
  requester_instruction: string | null;
  nlp_filled_fields: Record<string, NLPFilledField>;
}

export interface BackendValidation {
  completeness: string;
  missing_fields: string[];
  issues_detected: string[];
  preferred_supplier_status: {
    supplier: string | null;
    supplier_id: string | null;
    status: string;
    is_on_preferred_list: boolean;
    note: string;
  } | null;
}

export interface BackendApprovalThreshold {
  tier_id: string;
  rule_applied: string;
  threshold_currency: string;
  effective_contract_value: number;
  request_currency: string;
  fx_conversion_notes: string;
  quotes_required: number;
  fast_track_applied: boolean;
  approvers: string[];
  deviation_approval: string[];
  basis: string;
  note: string;
}

export interface BackendPolicyEvaluation {
  approval_threshold: BackendApprovalThreshold;
  preferred_supplier: {
    supplier: string | null;
    status: string;
    is_preferred: boolean;
    covers_delivery_country: boolean;
    is_restricted: boolean;
    policy_note: string;
  } | null;
  restricted_suppliers: Record<string, unknown>;
  category_rules_applied: Array<{
    rule_id: string;
    rule_type: string;
    rule_text: string;
    context: string;
    is_relaxing: boolean;
  }>;
  geography_rules_applied: unknown[];
}

export interface BackendSupplier {
  supplier_id: string;
  supplier_name: string;
  preferred: boolean;
  incumbent: boolean;
  pricing_tier: string;
  pricing_tier_applied: string;
  moq: number;
  unit_price: number;
  unit_price_standard: number;
  unit_price_expedited: number;
  pricing_currency: string;
  total_price: number;
  total_price_in_req_currency: number;
  req_currency: string;
  fx_applied: boolean;
  fx_rate: number | null;
  expedited_used: boolean;
  standard_lead_time_days: number;
  expedited_lead_time_days: number;
  lead_time_days: number;
  lead_time_feasible: boolean;
  lead_time_note: string;
  budget_sufficient: boolean;
  budget_note: string;
  quality_score: number;
  risk_score: number;
  esg_score: number;
  capacity_per_month: number;
  capacity_flag: boolean;
  data_residency_supported: boolean;
  covers_delivery_country: boolean;
  policy_compliant: boolean;
  score: number;
  recommendation_note: string;
  rank: number;
  score_weights: Record<string, number>;
  savings_pct_vs_budget: number;
}

export interface BackendEscalation {
  rule?: string;
  reason?: string;
  trigger?: string;
  escalate_to?: string;
  urgency?: string;
  note?: string;
  explanation?: string;
  [key: string]: any;
}

export interface BackendRecommendation {
  status: string;
  shortlist_count: number;
  quotes_required: number;
  top_supplier: string | null;
  top_supplier_total: number | null;
  all_infeasible_lead_time: boolean;
  all_over_budget: boolean;
  preferred_supplier_if_resolved: string | null;
  preferred_supplier_rationale: string;
  minimum_budget_required: number | null;
  minimum_budget_currency: string | null;
  reason: string;
}

export interface BackendAuditTrail {
  policies_checked: string[];
  supplier_ids_evaluated: string[];
  pricing_region_used: string;
  pricing_tiers_applied: string;
  expedited_evaluated: boolean;
  fx_rates_used: Record<string, number>;
  data_sources_used: string[];
  historical_awards_consulted: boolean;
  historical_award_note: string;
  historical_context: {
    has_direct_history: boolean;
    prior_awards: unknown[];
    note: string;
  };
  nlp_used: boolean;
  nlp_translation_applied: boolean;
  nlp_contradictions_detected: number;
  nlp_qty_override_applied: boolean;
  nlp_fields_filled: string[];
  scoring_weights_used: Record<string, number>;
}

export interface BackendPipelineMeta {
  nlp_enabled: boolean;
  rationale_enabled: boolean;
  calibration_auc: number;
  pipeline_version: string;
}

export interface BackendResult {
  request_id?: string;
  processed_at?: string;
  request_interpretation: BackendRequestInterpretation;
  validation: BackendValidation;
  policy_evaluation: BackendPolicyEvaluation;
  supplier_shortlist: BackendSupplier[];
  suppliers_excluded: unknown[];
  escalations: BackendEscalation[];
  recommendation: BackendRecommendation;
  audit_trail: BackendAuditTrail;
  _pipeline: BackendPipelineMeta;
  negotiation_levers?: NegotiationLever[];
  bundle_opportunities?: BundleOpportunity[];
  agentic_insights?: AgenticInsight[];
  escalation_cycle_insights?: EscalationCycleInsights;
}

export interface CycleProfile {
  escalation_target: string;
  rule_codes: string[];
  n: number;
  mean_days: number;
  median_days: number;
  p75_days: number;
  p90_days: number;
  p95_days: number;
  std_days: number;
  min_days: number;
  max_days: number;
  pct_on_time: number;
  trend_direction: 'IMPROVING' | 'STABLE' | 'WORSENING';
  trend_delta_days: number;
  insufficient_data: boolean;
}

export interface SegmentConcentration {
  category_l2: string;
  region: string;
  n_active_suppliers: number;
  total_awarded_eur: number;
  hhi: number;
  hhi_label: string;
  top_supplier_id: string;
  top_supplier_name: string;
  top_supplier_share_pct: number;
  top_3_share_pct: number;
  dependency_flag: boolean;
  single_source_risk: boolean;
  supplier_shares: Array<{
    supplier_name: string;
    share_pct: number;
    value_eur: number;
  }>;
}

export interface AnalyticsData {
  cycle_profiles: Record<string, CycleProfile>;
  concentration_segments: SegmentConcentration[];
}

export interface AgenticInsight {
  type: 'regional_constraint' | 'news_risk' | 'external_data';
  title: string;
  source: string;
  relevance: 'high' | 'medium' | 'low';
  summary: string;
  impact_score: number;
}

export interface EscalationCycleInsightItem {
  target: string;
  urgency: 'critical' | 'tight' | 'ok' | 'unknown';
  historical_mean_days: number;
  historical_median_days: number;
  historical_sample_size: number;
  scoped_to_business_unit: boolean;
  days_to_deadline: number | null;
  insight: string;
  recommended_action: string;
}

export interface EscalationCycleInsights {
  summary: string;
  days_to_deadline: number | null;
  insights: EscalationCycleInsightItem[];
}

