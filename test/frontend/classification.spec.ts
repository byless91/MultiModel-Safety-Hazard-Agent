import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { apiMock } = vi.hoisted(() => ({ apiMock: { post: vi.fn(), get: vi.fn() } }))
vi.mock('../../frontend/src/api/client', () => ({
  api: apiMock, getStoredToken: () => null, setStoredToken: () => undefined,
}))

import ClassificationPanel from '../../frontend/src/components/ClassificationPanel.vue'
import HumanReviewPanel from '../../frontend/src/components/HumanReviewPanel.vue'
import { useAssessmentStore } from '../../frontend/src/stores/assessment'
import { useAuthStore } from '../../frontend/src/stores/auth'
import type { Assessment } from '../../frontend/src/types'
import { makeAssessment } from './fixtures/assessment'

const taxonomy = { version: 'm1-v1', categories: ['占用疏散通道', '其他隐患'], tags: ['通道受阻', '待现场核实'] }
function item(): Assessment {
  return { ...makeAssessment(), record_mode: 'classification', risk_level: null, classification: {
    taxonomy_version: 'm1-v1', suggested_category: '占用疏散通道', suggested_tags: ['通道受阻'],
    final_tags: [], suggestion_status: 'suggested', warnings: [], is_demo: false, revision: 0,
  } }
}
const wrappers: ReturnType<typeof mount>[] = []
function panel(value = item()) {
  const wrapper = mount(ClassificationPanel, { props: { assessment: value }, global: {
    plugins: [ElementPlus], stubs: { HumanReviewPanel: true, LegalEvidence: true },
  } })
  wrappers.push(wrapper)
  return wrapper
}
beforeEach(() => {
  vi.resetAllMocks()
  sessionStorage.clear()
  setActivePinia(createPinia())
  apiMock.get.mockResolvedValue({ data: taxonomy })
})
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); document.body.innerHTML = '' })

describe('M1 classification entry', () => {
  it('keeps suggestions separate until explicitly adopted and saved, with no default risk', async () => {
    const wrapper = panel()
    await flushPromises()
    expect((wrapper.get('select').element as HTMLSelectElement).value).toBe('')
    expect(wrapper.text()).toContain('未分级')
    await wrapper.findAll('button').find(b => b.text() === '采用建议填写')!.trigger('click')
    expect(apiMock.post).not.toHaveBeenCalled()
    const saved = { ...item(), hazard_category: '占用疏散通道' }
    apiMock.post.mockResolvedValueOnce({ data: saved })
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(apiMock.post.mock.calls[0][1]).toEqual({ category: '占用疏散通道', tags: ['通道受阻'],
      risk_level: null, note: '', taxonomy_version: 'm1-v1', revision: 0 })
    expect(wrapper.emitted('updated')?.[0]).toEqual([saved])
  })

  it('retains input on failure and does not emit a false saved result', async () => {
    const wrapper = panel()
    await flushPromises()
    await wrapper.get('select').setValue('其他隐患')
    apiMock.post.mockRejectedValueOnce({ response: { data: { detail: '记录已变化，请刷新' } } })
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('记录已变化')
    expect((wrapper.get('select').element as HTMLSelectElement).value).toBe('其他隐患')
    expect(wrapper.emitted('updated')).toBeUndefined()
  })

  it.each(['unknown', 'failed', 'manual'] as const)('renders %s without pretending it is a category', async status => {
    const value = item()
    value.classification!.suggestion_status = status
    value.classification!.suggested_category = null
    const wrapper = panel(value)
    await flushPromises()
    expect(wrapper.text()).toContain(status === 'unknown' ? '未知类别' : status === 'failed' ? 'AI 分类失败' : '仅人工录入')
    expect(wrapper.findAll('button').some(b => b.text() === '采用建议填写')).toBe(false)
  })

  it('prevents approval while the human form has unsaved changes', async () => {
    const value = item()
    value.hazard_category = '占用疏散通道'
    value.classification!.revision = 1
    const wrapper = panel(value)
    await flushPromises()
    expect(wrapper.findComponent(HumanReviewPanel).props('loading')).toBe(false)
    await wrapper.get('select').setValue('其他隐患')
    expect(wrapper.findComponent(HumanReviewPanel).props('loading')).toBe(true)
    expect(wrapper.text()).toContain('有未保存的修改')
  })

  it('shows taxonomy loading failures with a retry instead of an unusable success state', async () => {
    apiMock.get.mockRejectedValueOnce(new Error('加载失败'))
    const wrapper = panel()
    await flushPromises()
    expect(wrapper.text()).toContain('重试加载分类选项')
    expect(wrapper.get('fieldset').attributes('disabled')).toBeDefined()
  })

  it('freezes the entry mode alongside the original payload for idempotent retries', async () => {
    const store = useAssessmentStore()
    apiMock.post.mockRejectedValueOnce(new Error('lost response')).mockResolvedValueOnce({ data: item() })
    await expect(store.create('现场描述', [], { entryMode: 'manual' })).rejects.toThrow()
    apiMock.get.mockRejectedValueOnce({ response: { status: 404 } })
    await store.retryCreate()
    expect((apiMock.post.mock.calls[0][1] as FormData).get('mode')).toBe('manual')
    expect((apiMock.post.mock.calls[1][1] as FormData).get('mode')).toBe('manual')
    expect(apiMock.post.mock.calls[0][2].headers).toEqual(apiMock.post.mock.calls[1][2].headers)
  })

  it('requires saved human entry before reviewer approval and offers no automatic-grade editing', () => {
    const auth = useAuthStore()
    auth.authMode = 'jwt'
    auth.credentialValid = true
    auth.user = { id: 'reviewer', username: 'reviewer', role: 'reviewer' }
    const wrapper = mount(HumanReviewPanel, { props: { assessment: item() }, global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    expect(wrapper.text()).toContain('请先保存人工录入')
    expect(wrapper.find('form').exists()).toBe(false)
  })
})
