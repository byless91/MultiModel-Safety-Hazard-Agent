/** 统一错误信息提取（B6/WP5.4：store 与视图共用） */
export function extractError(err: unknown): string {
  if (typeof err === 'object' && err !== null) {
    const anyErr = err as { response?: { data?: { detail?: unknown } }; message?: string }
    const detail = anyErr.response?.data?.detail
    if (typeof detail === 'string' && detail) return detail
    if (Array.isArray(detail)) {
      const messages = detail.flatMap((item) => {
        if (typeof item !== 'object' || item === null || typeof item.msg !== 'string') return []
        return [item.msg]
      })
      if (messages.length) return messages.join('；')
    }
    return anyErr.message || '请求失败，请稍后重试'
  }
  return String(err)
}
