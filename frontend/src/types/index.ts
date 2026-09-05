export interface AssessmentImage {
  id: string
  filename: string
  mime_type?: string
  size_bytes: number
  image_kind: string
  url?: string
}

export interface EvidenceItem {
  source: string
  text: string
  version: string
  tags: string[]
  score: number
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
  report?: AssessmentReport
  followup_questions: string[]
  followup_used: number
  confirmed: boolean
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
