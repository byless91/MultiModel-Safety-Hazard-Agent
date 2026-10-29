/** 整改闭环状态映射（B6/WP5.4 抽自 AssessmentResult，供面板与父组件共用） */
export const RECT_STEPS = [
  { value: 'open', label: '待分派' },
  { value: 'assigned', label: '已分派' },
  { value: 'rectifying', label: '整改中' },
  { value: 'pending_verification', label: '待验证' },
  { value: 'verified', label: '已验证' },
  { value: 'closed', label: '已关闭' },
] as const

export const RECT_LABELS: Record<string, string> = {
  open: '待分派',
  assigned: '已分派',
  rectifying: '整改中',
  pending_verification: '待验证',
  verified: '已验证',
  closed: '已关闭',
}

export const VERDICT_LABELS: Record<string, string> = {
  resolved_recommended: 'AI 建议判定已完成',
  not_resolved: 'AI 判定未完成',
  insufficient_evidence: '证据不足，无法评估',
  needs_review: '结论冲突，需人工复核',
}

export function rectStatusLabel(status?: string | null): string {
  return RECT_LABELS[status || ''] || '未开始整改'
}
