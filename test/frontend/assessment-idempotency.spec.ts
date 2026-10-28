import { flushPromises, shallowMount, RouterLinkStub } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { apiMock } = vi.hoisted(() => ({ apiMock: { post: vi.fn(), get: vi.fn() } }))
vi.mock('../../frontend/src/api/client', () => ({ api: apiMock }))

import { useAssessmentStore } from '../../frontend/src/stores/assessment'
import type { Assessment, JobOut } from '../../frontend/src/types'
import { loadSubmission } from '../../frontend/src/utils/submission'
import HomeView from '../../frontend/src/views/HomeView.vue'
import { makeAssessment } from './fixtures/assessment'

const STORAGE_KEY = 'safety_hazard_submission_v1'
const completed = (id = 'assessment-1'): Assessment => ({ ...makeAssessment(), id, status: 'completed' })
const networkError = () => new Error('Network timeout')
const missing = () => ({ response: { status: 404, data: { detail: '暂未找到本次提交' } } })
const job = (status: JobOut['status']): JobOut => ({
  id: 'job-1', assessment_id: 'assessment-1', kind: 'create', status, progress_step: 'analyze',
  created_at: '2026-10-28T00:00:00Z', updated_at: '2026-10-28T00:00:00Z',
})
const postedKey = (index = 0): string => apiMock.post.mock.calls[index][2].headers['Idempotency-Key']

beforeEach(() => {
  vi.resetAllMocks()
  sessionStorage.clear()
  setActivePinia(createPinia())
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

async function timedOutAttempt() {
  apiMock.post.mockRejectedValueOnce(networkError())
  const store = useAssessmentStore()
  await expect(store.create('敏感现场描述', [new File(['scene'], 'private-scene.png')])).rejects.toThrow('Network timeout')
  return store
}

describe('R4 submission identity and recovery', () => {
  it('gives each explicit new submission its own key, including identical inputs', async () => {
    apiMock.post.mockResolvedValueOnce({ data: completed('first') }).mockResolvedValueOnce({ data: completed('second') })
    const store = useAssessmentStore()
    await store.create('相同现场', [])
    await store.create('相同现场', [])
    expect(postedKey()).toMatch(/^submission_[a-f0-9]{32}$/)
    expect(postedKey(1)).not.toBe(postedKey())
    expect(apiMock.get).not.toHaveBeenCalled()
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull()
  })

  it('queries first, then reuses the same key and frozen payload only on a definite 404', async () => {
    const files = [new File(['original'], 'original.png')]
    apiMock.post.mockRejectedValueOnce(networkError()).mockResolvedValueOnce({ data: completed() })
    const store = useAssessmentStore()
    await expect(store.create('原描述', files)).rejects.toThrow()
    files.push(new File(['changed'], 'changed.png'))
    apiMock.get.mockRejectedValueOnce(missing())
    await store.retryCreate()
    expect(apiMock.get).toHaveBeenCalledWith(`/assessment-submissions/${postedKey()}`)
    expect(postedKey(1)).toBe(postedKey())
    const form = apiMock.post.mock.calls[1][1] as FormData
    expect(form.get('description')).toBe('原描述')
    expect(form.getAll('files')).toHaveLength(1)
    expect((form.get('files') as File).name).toBe('original.png')
  })

  it('recovers a lost response without another POST, even when the old replay window elapsed', async () => {
    const store = await timedOutAttempt()
    const key = postedKey()
    apiMock.get.mockResolvedValueOnce({ data: completed() })
    expect((await store.retryCreate()).id).toBe('assessment-1')
    expect(apiMock.post).toHaveBeenCalledTimes(1)
    expect(apiMock.get).toHaveBeenCalledWith(`/assessment-submissions/${key}`)
    expect(store.hasPendingSubmission).toBe(false)
  })

  it('does not resend when the recovery lookup also has an uncertain network failure', async () => {
    const store = await timedOutAttempt()
    apiMock.get.mockRejectedValueOnce(networkError())
    await expect(store.retryCreate()).rejects.toThrow('Network timeout')
    expect(apiMock.post).toHaveBeenCalledTimes(1)
    expect(store.submission?.key).toBe(postedKey())
    expect(store.canRetrySubmission).toBe(true)
  })

  it('keeps a sync failure record and only reads it on recovery', async () => {
    apiMock.post.mockRejectedValueOnce({ response: {
      status: 502, headers: { 'assessment-id': 'failed-1' }, data: { detail: '模型执行失败' },
    } })
    const store = useAssessmentStore()
    await expect(store.create('现场情况', [])).rejects.toBeDefined()
    expect(store.submission).toMatchObject({ assessmentId: 'failed-1', phase: 'failed' })
    expect(store.canRetrySubmission).toBe(false)
    apiMock.get.mockResolvedValueOnce({ data: { ...completed('failed-1'), status: 'failed' } })
    await expect(store.recoverCreate()).rejects.toThrow('原记录已保留')
    expect(apiMock.post).toHaveBeenCalledTimes(1)
    expect(store.hasPendingSubmission).toBe(true)
  })

  it('treats a sync pending replay as accepted, not as completion or a new submission', async () => {
    const store = await timedOutAttempt()
    apiMock.get.mockResolvedValueOnce({ data: { ...completed(), status: 'pending' } })
    expect((await store.recoverCreate()).status).toBe('pending')
    expect(store.submission).toMatchObject({ assessmentId: 'assessment-1', phase: 'pending' })
    expect(store.hasPendingSubmission).toBe(true)
    apiMock.get.mockResolvedValueOnce({ data: completed() })
    await store.recoverCreate()
    expect(store.hasPendingSubmission).toBe(false)
    expect(apiMock.post).toHaveBeenCalledTimes(1)
  })

  it('keeps the accepted assessment identity after async polling loses its response', async () => {
    vi.useFakeTimers()
    apiMock.post.mockResolvedValueOnce({ data: job('queued') })
    apiMock.get.mockRejectedValueOnce(networkError())
    const store = useAssessmentStore()
    const first = expect(store.create('现场情况', [])).rejects.toThrow('Network timeout')
    await vi.advanceTimersByTimeAsync(2000)
    await first
    expect(store.submission?.assessmentId).toBe('assessment-1')
    apiMock.get.mockResolvedValueOnce({ data: job('succeeded') }).mockResolvedValueOnce({ data: completed() })
    await store.retryCreate()
    expect(apiMock.post).toHaveBeenCalledTimes(1)
    expect(store.hasPendingSubmission).toBe(false)
  })

  it('persists only recovery metadata across reload and never description or photos', async () => {
    await timedOutAttempt()
    const persisted = sessionStorage.getItem(STORAGE_KEY)!
    expect(persisted).not.toContain('敏感现场描述')
    expect(persisted).not.toContain('private-scene.png')
    expect(Object.keys(JSON.parse(persisted)).sort()).toEqual(['assessmentId', 'key', 'phase'])
    setActivePinia(createPinia())
    const restored = useAssessmentStore()
    expect(restored.submission?.key).toBe(postedKey())
    expect(restored.canRetrySubmission).toBe(false)
    apiMock.get.mockResolvedValueOnce({ data: completed() })
    expect((await restored.recoverCreate()).id).toBe('assessment-1')
    expect(apiMock.post).toHaveBeenCalledTimes(1)
  })

  it('does not invent replacement files after reload when the server has no record yet', async () => {
    await timedOutAttempt()
    setActivePinia(createPinia())
    const store = useAssessmentStore()
    apiMock.get.mockRejectedValueOnce(missing())
    await expect(store.retryCreate()).rejects.toThrow('原照片未保留')
    expect(apiMock.post).toHaveBeenCalledTimes(1)
    expect(store.hasPendingSubmission).toBe(true)
  })

  it('requires an explicit new action before replacing an uncertain attempt', async () => {
    const store = await timedOutAttempt()
    const originalKey = postedKey()
    await expect(store.create('另一现场', [])).rejects.toThrow('先查询')
    expect(apiMock.post).toHaveBeenCalledTimes(1)
    store.startNewSubmission()
    apiMock.post.mockResolvedValueOnce({ data: completed() })
    await store.create('另一现场', [])
    expect(postedKey(1)).not.toBe(originalKey)
  })

  it('prevents concurrent double-clicks from minting and sending another attempt', async () => {
    let finish!: (value: { data: Assessment }) => void
    apiMock.post.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    const store = useAssessmentStore()
    const first = store.create('现场情况', [])
    await expect(store.create('现场情况', [])).rejects.toThrow('尚未确认')
    expect(() => store.startNewSubmission()).toThrow('尚未结束')
    expect(apiMock.post).toHaveBeenCalledTimes(1)
    finish({ data: completed() })
    await first
  })

  it.each([400, 401, 403, 413, 415, 422])('allows correction after definite pre-acceptance rejection %s', async (status) => {
    apiMock.post.mockRejectedValueOnce({ response: { status, data: { detail: '拒绝受理' } } })
    const store = useAssessmentStore()
    await expect(store.create('现场情况', [])).rejects.toBeDefined()
    const key = postedKey()
    expect(store.hasPendingSubmission).toBe(false)
    apiMock.post.mockResolvedValueOnce({ data: completed() })
    await store.create('修正后的情况', [])
    expect(postedKey(1)).not.toBe(key)
  })

  it('keeps a conflict key and exposes the original record for read-only recovery', async () => {
    apiMock.post.mockRejectedValueOnce({ response: {
      status: 409, headers: { 'assessment-id': 'original' }, data: { detail: '提交内容不同' },
    } })
    const store = useAssessmentStore()
    await expect(store.create('现场情况', [])).rejects.toBeDefined()
    expect(store.submission?.assessmentId).toBe('original')
    expect(store.hasPendingSubmission).toBe(true)
  })

  it.each([401, 403])('keeps recovery metadata when a lookup is rejected with %s', async (status) => {
    const store = await timedOutAttempt()
    const key = postedKey()
    apiMock.get.mockRejectedValueOnce({ response: { status, data: { detail: '需要重新登录' } } })
    await expect(store.retryCreate()).rejects.toBeDefined()
    expect(store.submission?.key).toBe(key)
    expect(loadSubmission()?.key).toBe(key)
    expect(apiMock.post).toHaveBeenCalledTimes(1)
  })

  it('works in memory when browser storage is unavailable', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('storage denied') })
    const store = await timedOutAttempt()
    apiMock.get.mockResolvedValueOnce({ data: completed() })
    await store.recoverCreate()
    expect(store.hasPendingSubmission).toBe(false)
  })

  it('ignores malformed stored metadata', () => {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ key: 'bad', assessmentId: 1, phase: 'pending' }))
    expect(loadSubmission()).toBeNull()
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ key: 12345678, assessmentId: null, phase: 'pending' }))
    expect(loadSubmission()).toBeNull()
  })
})

describe('HomeView recovery entry', () => {
  function mountHome() {
    return shallowMount(HomeView, { global: {
      directives: { loading: () => undefined },
      stubs: {
        ElCard: { template: '<section><slot /></section>' },
        ElButton: { props: ['disabled'], emits: ['click'],
          template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>' },
        ElIcon: { template: '<span><slot /></span>' },
        ElUpload: true, ElInput: true, ElAlert: true, Plus: true, UploadFilled: true,
        RouterLink: RouterLinkStub,
      },
    } })
  }

  it('shows a recoverable record link and prevents accidental fresh submission after a sync failure', async () => {
    apiMock.post.mockRejectedValueOnce({ response: {
      status: 502, headers: { 'assessment-id': 'failed-record' }, data: { detail: '模型执行失败' },
    } })
    const store = useAssessmentStore()
    await expect(store.create('现场情况', [])).rejects.toBeDefined()
    const wrapper = mountHome()
    expect(wrapper.text()).toContain('原记录已保留')
    expect(wrapper.text()).toContain('查询本次提交')
    expect(wrapper.text()).not.toContain('重试原内容')
    const link = wrapper.findAllComponents(RouterLinkStub).find((item) => item.text() === '查看研判记录')!
    expect(link.props('to')).toBe('/assessments/failed-record')
    const submit = wrapper.findAll('button').find((item) => item.text().includes('开始研判'))!
    expect(submit.attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('the visible query button recovers the original result without posting again', async () => {
    await timedOutAttempt()
    apiMock.get.mockResolvedValueOnce({ data: completed() })
    const wrapper = mountHome()
    await wrapper.findAll('button').find((item) => item.text() === '查询本次提交')!.trigger('click')
    await flushPromises()
    expect(apiMock.post).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).not.toContain('结果尚未确认')
    expect(wrapper.findComponent({ name: 'AssessmentResult' }).exists()).toBe(true)
    wrapper.unmount()
  })
})
