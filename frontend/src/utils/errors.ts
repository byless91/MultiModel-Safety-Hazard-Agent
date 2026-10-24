/** 统一错误信息提取（B6/WP5.4：store 与视图共用） */
export function extractError(err: unknown): string {
  if (typeof err === 'object' && err !== null) {
    const anyErr = err as { response?: { data?: { detail?: string } }; message?: string }
    return anyErr.response?.data?.detail || anyErr.message || '请求失败'
  }
  return String(err)
}
