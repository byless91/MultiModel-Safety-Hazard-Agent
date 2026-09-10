export interface AssessmentImage {
  id: string
  filename: string
  mime_type?: string
  size_bytes: number
  image_kind: string
  created_at?: string
  url?: string
}

export interface EvidenceItem {
  id?: string
  source: string
  document?: string
  article?: string
  effective_date?: string
  text?: string
  snippet?: string
  version: string
  tags: string[]
  score: number
  risk_type?: string
  scene?: string
  is_demo?: boolean
}

export interface FindingEvidenceStatus {
  finding_id: string
  category: string
  supported: boolean
  support_score: number
  evidence_ids: string[]
  unsupported_claims: string[]
  visual_evidence_ok: boolean
  needs_human_review: boolean
}

export interface EvidenceJudgeData {
  supported: boolean
  support_score: number
  evidence_ids: string[]
  unsupported_claims: string[]
  needs_human_review: boolean
  visual_evidence_count: number
  retrieval_evidence_count: number
  findings: FindingEvidenceStatus[]
  version: string
}

export interface FindingLocation {
  image_id?: string
  bbox?: number[]
  location_text?: string
}

export interface ModelHazardOutput {
  hazard_type: string
  description?: string
  severity?: number
  confidence?: number
  observed_facts?: string[]
  uncertainties?: string[]
  location?: FindingLocation | null
}

export interface ModelAnalysisData {
  scene_summary?: string
  observations?: string[]
  hazard_hints?: string[]
  keywords?: string[]
  vision_confidence?: number
  hazards?: ModelHazardOutput[]
}

export interface ModelRunResult {
  provider: string
  family: string
  model: string
  model_version: string
  status: string
  error_type: string
  error_message: string
  latency_ms: number
  retry_count: number
  analysis: ModelAnalysisData | null
}

export interface DisagreementData {
  mode: string
  agreement_available: boolean
  agreement_score: number
  category_agreement: boolean
  severity_difference: number | null
  critical_conflict: boolean
  need_human_review: boolean
  reasons: string[]
  pairs: DisagreementPair[]
  model_count: number
  compared_models: string[]
}

export interface DisagreementPair {
  category: string
  family_a: string
  family_b: string
  severity_a: number | null
  severity_b: number | null
  confidence_a: number
  confidence_b: number
  severity_difference: number | null
  category_score: number
  severity_score: number
  factual_conflict: boolean
}

export interface Finding {
  finding_id: string
  category: string
  description: string
  final_severity?: number
  final_confidence: number
  observed_facts: string[]
  uncertainties: string[]
  model_support: string[]
  locations: FindingLocation[]
  source: string
  evidence_status: string
  evidence_ids: string[]
  support_score?: number
  unsupported_claims?: string[]
  risk_score?: number | null
  risk_level?: string | null
}

export interface WorkOrder {
  title: string
  category: string
  level: string
  deadline: string
  location: string
  items: string[]
  acceptance: string
  source_note: string
}

export interface RectificationComparisonPair {
  index: number
  original_id: string
  rectification_id: string
  original_url?: string | null
  rectification_url?: string | null
}

export interface RectificationComparison {
  original_count: number
  rectification_count: number
  pair_count: number
  unmatched_original_count: number
  unmatched_rectification_count: number
  paired: RectificationComparisonPair[]
}

export type RectificationVerdict =
  | 'resolved_recommended'
  | 'not_resolved'
  | 'insufficient_evidence'
  | 'needs_review'

export interface RectificationAssessment {
  completion_score: number | null
  completion_confidence: number
  verdict: RectificationVerdict
  review_required: boolean
  triggered_rules: string[]
  reasons: string[]
  provider_ok: boolean
  rule_version: string
}

export interface HumanReviewResolution {
  confirmed: boolean
  reviewer?: string
  note?: string
  edits?: Record<string, unknown>
  resolved_at?: string
}

export interface AssessmentReport {
  summary: string
  briefing: string
  category: string
  level: number
  confidence: number
  evidence_count: number
  legal_basis: EvidenceItem[]
  immediate_actions: string[]
  long_term_actions: string[]
  work_order: WorkOrder
  disclaimer: string
}

export type AssessmentStatus =
  | 'pending'
  | 'processing'
  | 'needs_more_info'
  | 'completed'
  | 'needs_review'
  | 'awaiting_human_review'
  | 'confirmed'

export type RectificationStatus =
  | 'open'
  | 'assigned'
  | 'rectifying'
  | 'pending_verification'
  | 'verified'
  | 'closed'

export interface RectificationHistoryEntry {
  action: string
  from_status: string
  to_status: string
  note: string
  by: string
  created_at: string
}

export interface Assessment {
  id: string
  description: string
  status: AssessmentStatus
  scene_summary?: string
  hazard_category?: string
  risk_level?: number
  confidence?: number
  conclusion?: string
  evidence: EvidenceItem[]
  evidence_judge?: EvidenceJudgeData | null
  multi_model?: {
    ensemble_mode: string
    succeeded: number
    failed: number
    total_latency_ms: number
    primary: ModelRunResult
    results: ModelRunResult[]
  } | null
  disagreement?: DisagreementData | null
  findings?: Finding[]
  report?: AssessmentReport
  followup_questions: string[]
  followup_used: number
  confirmed: boolean
  review_reasons?: string[]
  awaiting_human_review?: boolean
  human_review?: {
    need_human_review: boolean
    review_reasons: string[]
    triggers: Record<string, boolean>
    resolution?: HumanReviewResolution | null
  } | null
  risk_result?: {
    risk_score: number
    risk_level: string
    operational_level: number
    factor_scores: Record<string, number>
    rule_weights: Record<string, number>
    severity_hint?: number | null
    rule_version: string
    evidence_used: string[]
    triggered_rules: string[]
    review_suggestion: boolean
  } | null
  risk_score?: number
  risk_label?: 'low' | 'medium' | 'high'
  risk_operational_level?: number
  risk_rule_version?: string
  risk_factors?: Record<string, number>
  risk_evidence_used?: string[]
  risk_triggered_rules?: string[]
  risk_review_suggestion?: boolean
  rectification_status?: RectificationStatus | null
  rectification_note?: string
  rectification_score?: number
  rectification_analysis?: {
    completion_score?: number
    status_hint?: string
    summary?: string
    issues?: string[]
    reasons?: string[]
    comparison?: RectificationComparison | null
    assessment?: RectificationAssessment | null
  }
  rectification_meta?: {
    current_status?: string
    history: RectificationHistoryEntry[]
  } | null
  rectification_next_states?: RectificationStatus[]
  rectified_at?: string
  created_at: string
  updated_at: string
  images: AssessmentImage[]
}

export interface KnowledgeDocument {
  id: string
  title: string
  source?: string
  version?: string
  status: string
  created_at: string
}

export interface KnowledgeDocumentDetail extends KnowledgeDocument {
  content: string
}

export interface EvaluationMetrics {
  total: number
  category_accuracy?: number | null
  level_accuracy?: number | null
  severity_mae?: number | null
  level_accuracy_tolerance1?: number | null
  clause_hit_rate?: number | null
  evidence_hit_rate?: number | null
  evidence_support_rate?: number | null
  unsupported_claim_rate?: number | null
  model_conflict_rate?: number | null
  human_review_rate?: number | null
  human_review_count?: number
  unsafe_auto_pass_count?: number
  unsafe_auto_pass_rate?: number | null
  unsafe_hazard_base_count?: number
  false_positive_count?: number
  false_negative_count?: number
  evidence_failure_count?: number
  severity_error_count?: number
  model_conflict_count?: number
  avg_latency_s?: number | null
}

export interface EvaluationFailureCase {
  case_id: string
  scenario?: string
  expected?: string
  predicted?: string
  status?: string
  flags: string[]
  reasons?: Array<{ type: string; reason: string }>
}

export interface AblationVariant {
  label: string
  mode?: string
  metrics: EvaluationMetrics
}

export interface AblationReport {
  dataset_version?: string
  case_count?: number
  provider_mode?: string
  evaluation_mode?: string
  source_type_counts?: Record<string, number>
  partitions?: Record<string, number>
  variants: Record<string, AblationVariant>
}

export interface EvaluationReport {
  dataset_version?: string
  title?: string
  dataset_case_count?: number
  source_type_counts?: Record<string, number>
  category_counts?: Record<string, number>
  severity_counts?: Record<string, number>
  scenario_breakdown?: Record<
    string,
    {
      total: number
      category_accuracy: number
      level_accuracy: number
      clause_hit_rate: number
      review_rate: number
    }
  >
  dataset_overview?: {
    case_count: number
    source_type_counts: Record<string, number>
    category_counts: Record<string, number>
    severity_counts: Record<string, number>
    scenario_counts: Record<string, number>
    hazard_case_count: number
    safe_negative_case_count: number
    image_case_count: number
    limitation_notes: string[]
  }
  model_family_performance?: Array<{
    family: string
    attempts: number
    category_accuracy: number
    level_accuracy: number
  }>
  evidence_stats_summary?: {
    supported_count: number
    insufficient_count: number
    supported_rate: number
    insufficient_rate: number
  }
  review_and_risk_stats?: {
    high_risk_case_count: number
    risk_review_suggestion_count: number
    risk_review_suggestion_rate: number
    average_risk_score: number
  }
  error_summary?: {
    counts: Record<string, number>
    total_error_occurrences: number
    cases_with_error: number
  }
  error_analysis?: EvaluationFailureCase[]
  ablation_study?: AblationReport | null
  evaluation_mode?: string
  evaluation_timestamp?: string
  provider?: string
  variant?: string
  metrics: EvaluationMetrics
}

export interface EvaluationReportsPayload {
  evaluation_report: EvaluationReport | null
  ablation_report: AblationReport | null
  evaluation_report_modified_at?: string | null
  ablation_report_modified_at?: string | null
  has_trace_results?: boolean
  source_dir?: string
}
