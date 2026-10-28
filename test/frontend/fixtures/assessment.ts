import type { Assessment } from '../../../frontend/src/types'

export function makeAssessment(): Assessment {
  return {
    id: 'r0-offline-assessment',
    description: 'R0_TEST_ONLY_EVIDENCE',
    status: 'awaiting_human_review',
    evidence: [],
    findings: [],
    followup_questions: [],
    followup_used: 0,
    confirmed: false,
    images: [],
    created_at: '2026-10-28T00:00:00Z',
    updated_at: '2026-10-28T00:00:00Z',
  }
}
