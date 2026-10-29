import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    post: vi.fn(),
    get: vi.fn(),
  },
}))

vi.mock('../../api/client', () => ({
  api: apiMock,
  getStoredToken: () => null,
  setStoredToken: () => undefined,
}))

import { useAssessmentStore } from '../assessment'
import type { Assessment, JobOut } from '../../types'

function makeAssessment(id: string): Assessment {
  return {
    id,
    description: '楼道堆物',
    status: 'completed',
    evidence: [],
    images: [],
    followup_questions: [],
    followup_used: 0,
    confirmed: false,
    awaiting_human_review: false,
    created_at: '2026-01-01T00:00:00',
    updated_at: '2026-01-01T00:00:00',
  } as unknown as Assessment
}

function makeJob(assessmentId: string, status: JobOut['status']): JobOut {
  return {
    id: 'job-1',
    assessment_id: assessmentId,
    kind: 'create',
    status,
    progress_step: 'analyze',
    created_at: '2026-01-01T00:00:00',
    updated_at: '2026-01-01T00:00:00',
  }
}

describe('assessment store（B6/WP5.4）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('sync 模式：直接返回 Assessment，不轮询', async () => {
    const expected = makeAssessment('a-1')
    apiMock.post.mockResolvedValueOnce({ data: expected })
    const store = useAssessmentStore()
    const result = await store.create('楼道堆物', [])
    expect(result.id).toBe('a-1')
    expect(apiMock.post).toHaveBeenCalledTimes(1)
    expect(apiMock.get).not.toHaveBeenCalled()
    expect(store.activeJob).toBeNull()
  })

  it('async 模式：202 返回 JobOut 后轮询直至 succeeded 再取回结果', async () => {
    const assessment = makeAssessment('a-2')
    apiMock.post.mockResolvedValueOnce({ data: makeJob('a-2', 'queued') })
    apiMock.get
      .mockResolvedValueOnce({ data: makeJob('a-2', 'running') })
      .mockResolvedValueOnce({ data: makeJob('a-2', 'succeeded') })
      .mockResolvedValueOnce({ data: assessment })
    const store = useAssessmentStore()

    vi.useFakeTimers()
    const pending = store.create('楼道堆物', [])
    // 两轮轮询（2s 间隔）
    await vi.advanceTimersByTimeAsync(2000)
    await vi.advanceTimersByTimeAsync(2000)
    const result = await pending
    vi.useRealTimers()

    expect(result.id).toBe('a-2')
    expect(apiMock.get).toHaveBeenCalledTimes(3) // 两次 job 轮询 + 一次取结果
    expect(store.activeJob?.status).toBe('succeeded')
  })

  it('async 模式：任务失败时抛出错误并保留 job 状态', async () => {
    const failed = makeJob('a-3', 'failed')
    failed.error = '模型服务不可用'
    apiMock.post.mockResolvedValueOnce({ data: makeJob('a-3', 'queued') })
    apiMock.get.mockResolvedValueOnce({ data: failed })
    const store = useAssessmentStore()

    vi.useFakeTimers()
    const pending = store.create('楼道堆物', [])
    const expectation = expect(pending).rejects.toThrow('模型服务不可用')
    await vi.advanceTimersByTimeAsync(2000)
    await expectation
    vi.useRealTimers()

    expect(store.activeJob?.status).toBe('failed')
    expect(store.error).toBe('模型服务不可用')
  })

  it('followup 同样支持 async 轮询', async () => {
    const assessment = makeAssessment('a-4')
    apiMock.post.mockResolvedValueOnce({ data: makeJob('a-4', 'queued') })
    apiMock.get
      .mockResolvedValueOnce({ data: makeJob('a-4', 'succeeded') })
      .mockResolvedValueOnce({ data: assessment })
    const store = useAssessmentStore()

    vi.useFakeTimers()
    const pending = store.followup('a-4', '补充信息')
    await vi.advanceTimersByTimeAsync(2000)
    const result = await pending
    vi.useRealTimers()

    expect(result.id).toBe('a-4')
    expect(apiMock.post).toHaveBeenCalledWith(
      '/assessments/a-4/followup',
      { answer: '补充信息' },
    )
  })
})
