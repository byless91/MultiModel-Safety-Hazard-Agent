export interface AssessmentImage {
  id: string
  filename: string
  mime_type?: string
  size_bytes: number
  image_kind: string
  url?: string
}

export interface EvidenceItem {
  id?: string
  source: string
  article?: string
  effective_date?: string
  text?: string
  snippet?: string
  version: string
  tags: string[]
  score: number
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
  } | null
  risk_result?: {
    risk_score: number
    risk_level: string
    operational_level: number
    factor_scores: Record<string, number>
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
  rectification_status?: 'pending' | 'under_review' | 'resolved'
  rectification_note?: string
  rectification_score?: number
  rectification_analysis?: {
    completion_score?: number
    status_hint?: string
    summary?: string
    issues?: string[]
    reasons?: string[]
  }
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
