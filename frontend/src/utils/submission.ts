import type { EntryMode, RecordMetadata } from '../types'

/** Persist only recovery metadata; descriptions and files stay in memory. */
export interface SubmissionAttempt {
  key: string
  assessmentId: string | null
  phase: 'uncertain' | 'pending' | 'failed' | 'resolved'
}

export interface SubmissionPayload {
  description: string
  files: File[]
  mode: EntryMode
  metadata?: RecordMetadata
}

const STORAGE_KEY = 'safety_hazard_submission_v1'
const PHASES = ['uncertain', 'pending', 'failed', 'resolved']

export function loadSubmission(): SubmissionAttempt | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null')
    if (!value || typeof value.key !== 'string' || !/^[A-Za-z0-9_-]{8,128}$/.test(value.key)) return null
    if (!PHASES.includes(value.phase)) return null
    if (value.assessmentId !== null && typeof value.assessmentId !== 'string') return null
    if (value.phase === 'resolved') return null
    return { key: value.key, assessmentId: value.assessmentId, phase: value.phase }
  } catch {
    return null
  }
}

export function saveSubmission(value: SubmissionAttempt | null): void {
  try {
    if (!value || value.phase === 'resolved') sessionStorage.removeItem(STORAGE_KEY)
    else sessionStorage.setItem(STORAGE_KEY, JSON.stringify(value))
  } catch {
    // Restricted storage must not prevent an in-memory submission or recovery.
  }
}

export function newSubmission(): SubmissionAttempt {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  const key = `submission_${Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')}`
  return { key, assessmentId: null, phase: 'uncertain' }
}

export function submissionError(err: unknown): { status?: number; assessmentId?: string } {
  if (typeof err !== 'object' || err === null || !('response' in err)) return {}
  const response = err.response as { status?: number; headers?: Record<string, unknown> } | undefined
  const id = response?.headers?.['assessment-id'] || response?.headers?.['Assessment-Id']
  return { status: response?.status, assessmentId: typeof id === 'string' && id.length <= 64 ? id : undefined }
}
