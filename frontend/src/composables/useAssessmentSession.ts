import { computed, onScopeDispose, ref } from 'vue'
import { api } from '../api/client'
import { useAssessmentStore } from '../stores/assessment'
import type { Assessment, JobOut } from '../types'
import { extractError } from '../utils/errors'

/** One page owns one observation session; stopping it never cancels a server job. */
export function useAssessmentSession() {
  const store = useAssessmentStore()
  const assessment = ref<Assessment | null>(null)
  const job = ref<JobOut | null>(null)
  const busy = ref(false)
  const waiting = ref(false)
  const error = ref('')
  const notice = ref('')
  const working = computed(() => job.value?.status === 'queued' || job.value?.status === 'running')
  let controller = new AbortController()
  let timer: ReturnType<typeof setTimeout> | undefined
  let generation = 0
  let disposed = false
  let deadline = 0

  function stop() {
    generation++
    controller.abort()
    clearTimeout(timer)
    timer = undefined
    busy.value = false
  }
  onScopeDispose(() => { disposed = true; stop() })

  function begin() {
    stop()
    if (disposed) return null
    controller = new AbortController()
    deadline = Date.now() + 120_000
    waiting.value = false
    error.value = ''
    notice.value = ''
    return { token: generation, signal: controller.signal }
  }
  function current(token: number) { return !disposed && token === generation && !controller.signal.aborted }
  function schedule(id: string, token: number) {
    if (!current(token)) return
    if (Date.now() >= deadline) {
      waiting.value = true
      notice.value = '本地等待已结束，服务端任务可能仍在执行。可继续查询或稍后从历史记录进入。'
      return
    }
    timer = setTimeout(() => { void inspect(id, token) }, Math.min(2000, deadline - Date.now()))
  }
  function setAssessment(value: Assessment) {
    assessment.value = value
    store.finishSubmission(value)
  }
  async function inspect(id: string, token: number) {
    if (!current(token)) return
    if (Date.now() >= deadline) { schedule(id, token); return }
    try {
      let latest: JobOut | null = null
      try {
        const response = await api.get<JobOut>(`/assessments/${id}/job`, { signal: controller.signal })
        latest = response.data
      } catch (err) {
        if ((err as { response?: { status?: number } }).response?.status !== 404) throw err
      }
      if (!current(token)) return
      if (latest && latest.assessment_id !== id) throw new Error('任务与研判记录不匹配，请重新查询')
      job.value = latest
      error.value = ''
      notice.value = ''
      if (latest && ['queued', 'running'].includes(latest.status)) { schedule(id, token); return }
      const { data } = await api.get<Assessment>(`/assessments/${id}`, { signal: controller.signal })
      if (!current(token)) return
      if (data.id !== id) throw new Error('研判记录不匹配，请重新查询')
      setAssessment(data)
      if (!latest && ['pending', 'processing'].includes(data.status)) {
        waiting.value = true
        notice.value = '暂未找到对应任务，请继续查询记录。'
      }
      if (latest?.status === 'failed') error.value = latest.error || '研判任务执行失败，原记录已保留。'
    } catch (err) {
      if (!current(token)) return
      error.value = extractError(err)
      const status = (err as { response?: { status?: number } }).response?.status
      if (status === 401 || status === 403) { waiting.value = true; return }
      notice.value = '连接暂时中断，保留当前记录并自动重试查询。'
      schedule(id, token)
    }
  }
  async function open(id: string, initial?: Assessment) {
    const operation = begin()
    if (!operation) return
    assessment.value = initial ?? null
    job.value = null
    busy.value = true
    try {
      const value = initial ?? (await api.get<Assessment>(`/assessments/${id}`, { signal: operation.signal })).data
      if (!current(operation.token)) return
      if (value.id !== id) throw new Error('研判记录不匹配，请重新查询')
      setAssessment(value)
      await inspect(id, operation.token)
    } catch (err) {
      if (current(operation.token)) { error.value = extractError(err); waiting.value = true }
    } finally {
      if (current(operation.token)) busy.value = false
    }
  }
  async function run(action: (signal: AbortSignal) => Promise<Assessment>) {
    const operation = begin()
    if (!operation) return
    busy.value = true
    job.value = null
    try {
      const value = await action(operation.signal)
      if (!current(operation.token)) return
      setAssessment(value)
      await inspect(value.id, operation.token)
    } catch (err) {
      if (current(operation.token)) { error.value = extractError(err); waiting.value = true }
    } finally {
      if (current(operation.token)) busy.value = false
    }
  }
  async function resume() {
    const id = assessment.value?.id
    if (id) await open(id, assessment.value ?? undefined)
  }
  function update(value: Assessment) {
    if (assessment.value?.id === value.id) setAssessment(value)
  }
  function clear() {
    stop()
    assessment.value = null
    job.value = null
    error.value = notice.value = ''
    waiting.value = false
  }
  return { assessment, job, busy, waiting, working, error, notice, open, run, resume, update, clear, stop }
}
