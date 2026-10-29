/** 展示层格式化工具（B6/WP5.4 抽自 AssessmentResult） */
export function formatTime(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString()
}
