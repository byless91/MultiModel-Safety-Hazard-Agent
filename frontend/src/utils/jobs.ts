export interface TaskOptions {
  wait?: boolean
  signal?: AbortSignal
}

export function waitForPoll(milliseconds: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException('本地等待已停止', 'AbortError'))
    const abort = () => {
      clearTimeout(timer)
      reject(new DOMException('本地等待已停止', 'AbortError'))
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', abort)
      resolve()
    }, milliseconds)
    signal?.addEventListener('abort', abort, { once: true })
  })
}
