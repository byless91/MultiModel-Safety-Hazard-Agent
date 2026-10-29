import { createPinia, setActivePinia } from 'pinia'
import { effectScope } from 'vue'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { apiMock } = vi.hoisted(() => ({ apiMock: { get: vi.fn(), post: vi.fn() } }))
vi.mock('../../frontend/src/api/client', () => ({ api: apiMock, getStoredToken: () => null, setStoredToken: () => {} }))
import { useAssessmentSession } from '../../frontend/src/composables/useAssessmentSession'
import { useAssessmentStore } from '../../frontend/src/stores/assessment'
import AssessmentDetailView from '../../frontend/src/views/AssessmentDetailView.vue'
import JobProgress from '../../frontend/src/components/JobProgress.vue'
import type { Assessment, JobOut } from '../../frontend/src/types'
import { makeAssessment } from './fixtures/assessment'

const scopes: ReturnType<typeof effectScope>[] = []
const wrappers: ReturnType<typeof shallowMount>[] = []
let records: Record<string, Assessment>
let jobs: Record<string, JobOut>
function job(id: string, status: JobOut['status'] = 'running'): JobOut {
  return { id: `job-${id}`, assessment_id: id, kind: 'create', status, progress_step: 'analyze',
    created_at: '2026-10-29T00:00:00Z', updated_at: '2026-10-29T00:00:00Z' }
}
function session() {
  const scope = effectScope()
  scopes.push(scope)
  return { value: scope.run(() => useAssessmentSession())!, scope }
}
beforeEach(() => {
  vi.useFakeTimers()
  setActivePinia(createPinia())
  sessionStorage.clear()
  vi.clearAllMocks()
  records = { a: { ...makeAssessment(), id: 'a', status: 'pending' }, b: { ...makeAssessment(), id: 'b', status: 'pending' } }
  jobs = { a: job('a'), b: job('b') }
  apiMock.get.mockImplementation(async (url: string) => {
    const id = url.split('/')[2]
    const data = url.endsWith('/job') ? jobs[id] : records[id]
    if (!data) throw { response: { status: 404, data: { detail: '记录不存在' } } }
    return { data: structuredClone(data) }
  })
})
afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  scopes.splice(0).forEach((scope) => scope.stop())
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('R7 task recovery sessions', () => {
  it('recovers queued/running jobs and stops on succeeded + needs_more_info', async () => {
    jobs.a.status = 'queued'
    const { value } = session()
    await value.open('a')
    expect(value.job.value?.status).toBe('queued')
    jobs.a.status = 'running'
    await vi.advanceTimersByTimeAsync(2000)
    expect(value.job.value?.status).toBe('running')
    jobs.a.status = 'succeeded'
    records.a.status = 'needs_more_info'
    await vi.advanceTimersByTimeAsync(2000)
    expect(value.assessment.value?.status).toBe('needs_more_info')
    const calls = apiMock.get.mock.calls.length
    await vi.advanceTimersByTimeAsync(20000)
    expect(apiMock.get).toHaveBeenCalledTimes(calls)
  })

  it('two minutes ends local waiting, retains running status and resumes using GET only', async () => {
    const { value } = session()
    await value.open('a')
    await vi.advanceTimersByTimeAsync(120000)
    expect(value.waiting.value).toBe(true)
    expect(value.job.value?.status).toBe('running')
    expect(value.notice.value).toContain('服务端任务可能仍在执行')
    const count = apiMock.get.mock.calls.length
    jobs.a.status = 'succeeded'
    records.a.status = 'awaiting_human_review'
    await vi.advanceTimersByTimeAsync(30000)
    expect(apiMock.get).toHaveBeenCalledTimes(count)
    await value.resume()
    expect(value.assessment.value?.status).toBe('awaiting_human_review')
    expect(value.waiting.value).toBe(false)
    expect(apiMock.post).not.toHaveBeenCalled()
  })

  it('recovers after a temporary polling network failure', async () => {
    const { value } = session()
    await value.open('a')
    apiMock.get.mockRejectedValueOnce(new Error('网络短断'))
    await vi.advanceTimersByTimeAsync(2000)
    expect(value.notice.value).toContain('自动重试')
    jobs.a.status = 'succeeded'
    records.a.status = 'completed'
    await vi.advanceTimersByTimeAsync(2000)
    expect(value.error.value).toBe('')
    expect(value.assessment.value?.status).toBe('completed')
  })

  it('failure stops polling and preserves the original record', async () => {
    const { value } = session()
    jobs.a = { ...job('a', 'failed'), error: '模型服务不可用' }
    records.a.status = 'needs_more_info'
    await value.open('a')
    expect(value.error.value).toBe('模型服务不可用')
    expect(value.assessment.value?.id).toBe('a')
    const calls = apiMock.get.mock.calls.length
    await vi.advanceTimersByTimeAsync(10000)
    expect(apiMock.get).toHaveBeenCalledTimes(calls)
  })

  it('unmount aborts in-flight reads and timers without cancelling the server job', async () => {
    const { value, scope } = session()
    await value.open('a')
    const signal = apiMock.get.mock.calls[1][1].signal as AbortSignal
    scope.stop()
    expect(signal.aborted).toBe(true)
    const calls = apiMock.get.mock.calls.length
    await vi.advanceTimersByTimeAsync(10000)
    expect(apiMock.get).toHaveBeenCalledTimes(calls)
    expect(apiMock.post).not.toHaveBeenCalled()
  })

  it('ignores a late record response after navigating to a different id', async () => {
    let resolve!: (value: { data: Assessment }) => void
    apiMock.get.mockImplementationOnce(() => new Promise((finish) => { resolve = finish }))
    const { value } = session()
    const first = value.open('a')
    await value.open('b')
    resolve({ data: records.a })
    await first
    expect(value.assessment.value?.id).toBe('b')
    expect(value.job.value?.assessment_id).toBe('b')
  })

  it('does not share state or completion between independent page sessions', async () => {
    const a = session().value
    const b = session().value
    await Promise.all([a.open('a'), b.open('b')])
    jobs.a.status = 'succeeded'
    records.a.status = 'completed'
    await vi.advanceTimersByTimeAsync(2000)
    expect(a.assessment.value?.status).toBe('completed')
    expect(b.job.value?.status).toBe('running')
    expect(b.assessment.value?.id).toBe('b')
  })

  it.each([401, 403])('pauses on HTTP %s without a retry loop', async (status) => {
    const { value } = session()
    await value.open('a')
    apiMock.get.mockRejectedValueOnce({ response: { status, data: { detail: '权限不足' } } })
    await vi.advanceTimersByTimeAsync(2000)
    const calls = apiMock.get.mock.calls.length
    expect(value.waiting.value).toBe(true)
    await vi.advanceTimersByTimeAsync(10000)
    expect(apiMock.get).toHaveBeenCalledTimes(calls)
  })

  it('accepts sync records without a job and does not poll forever', async () => {
    delete jobs.a
    records.a.status = 'completed'
    const { value } = session()
    await value.open('a')
    expect(value.job.value).toBeNull()
    expect(value.waiting.value).toBe(false)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('offers recovery for a pending record without a job', async () => {
    delete jobs.a
    const { value } = session()
    await value.open('a')
    expect(value.notice.value).toContain('暂未找到对应任务')
    expect(value.waiting.value).toBe(true)
  })

  it('rejects mismatched job identities', async () => {
    jobs.a = job('b')
    const { value } = session()
    await value.open('a')
    expect(value.job.value).toBeNull()
    expect(value.error.value).toContain('不匹配')
  })

  it('updates the route id in a reused detail component and displays pending state without a report', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/assessments/:id', component: AssessmentDetailView }] })
    await router.push('/assessments/a')
    const wrapper = shallowMount(AssessmentDetailView, { global: { plugins: [router],
      stubs: { ElButton: true, ElIcon: true, ArrowLeft: true, ElSkeleton: true, ElAlert: true } } })
    wrappers.push(wrapper)
    await flushPromises()
    expect(wrapper.findComponent(JobProgress).props('job')?.assessment_id).toBe('a')
    await router.push('/assessments/b')
    await flushPromises()
    expect(wrapper.findComponent(JobProgress).props('job')?.assessment_id).toBe('b')
  })

  it('new async UI actions return the accepted pending record without starting a global wait loop', async () => {
    apiMock.post.mockResolvedValueOnce({ data: job('a', 'queued') })
    const store = useAssessmentStore()
    const accepted = await store.create('现场描述', [], { wait: false })
    expect(accepted.id).toBe('a')
    expect(store.hasPendingSubmission).toBe(true)
    expect(vi.getTimerCount()).toBe(0)
    store.finishSubmission({ ...accepted, status: 'completed' })
    expect(store.hasPendingSubmission).toBe(false)
  })
})
