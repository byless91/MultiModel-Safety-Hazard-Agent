import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { apiMock } = vi.hoisted(() => ({ apiMock: { post: vi.fn(), get: vi.fn() } }))
vi.mock('../../frontend/src/api/client', () => ({
  api: apiMock, getStoredToken: () => null, setStoredToken: () => undefined,
}))

import HumanReviewPanel from '../../frontend/src/components/HumanReviewPanel.vue'
import RectificationPanel from '../../frontend/src/components/RectificationPanel.vue'
import { useAuthStore } from '../../frontend/src/stores/auth'
import { useAssessmentStore } from '../../frontend/src/stores/assessment'
import type { Assessment } from '../../frontend/src/types'
import { extractError } from '../../frontend/src/utils/errors'
import { makeAssessment } from './fixtures/assessment'

function assessment(): Assessment {
  return { ...makeAssessment(), hazard_category: '占用疏散通道', risk_level: 1, conclusion: 'AI 原始结论' }
}

function role(value = 'reviewer') {
  const auth = useAuthStore()
  auth.authMode = 'jwt'
  auth.credentialValid = true
  auth.user = { id: value, username: value, role: value }
}

const wrappers: ReturnType<typeof mount>[] = []
function panel(item = assessment()) {
  const wrapper = mount(HumanReviewPanel, { props: { assessment: item }, global: { plugins: [ElementPlus] } })
  wrappers.push(wrapper)
  return wrapper
}

beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks(); role() })
afterEach(() => { wrappers.splice(0).forEach((wrapper) => wrapper.unmount()); document.body.innerHTML = '' })

describe('R7 review actions', () => {
  it.each(['reviewer', 'admin'])('allows %s approval with notes and only emits server-confirmed state', async (value) => {
    role(value)
    const item = assessment()
    const saved = { ...item, status: 'confirmed', confirmed: true }
    apiMock.post.mockResolvedValueOnce({ data: saved })
    const wrapper = panel(item)
    await wrapper.get('textarea').setValue('已现场核实')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(apiMock.post).toHaveBeenCalledWith(`/assessments/${item.id}/confirm`, {
      confirmed: true, edits: {}, note: '已现场核实',
    })
    expect(wrapper.emitted('updated')?.[0]).toEqual([saved])
  })

  it('requires a non-whitespace rejection note and retains the rejected state', async () => {
    const wrapper = panel()
    await wrapper.findAll('input[type=radio]')[1].setValue(true)
    await wrapper.get('textarea').setValue('  ')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('[role=alert]').text()).toContain('填写复核意见')
    expect(apiMock.post).not.toHaveBeenCalled()
    apiMock.post.mockResolvedValueOnce({ data: { ...assessment(), status: 'needs_review' } })
    await wrapper.get('textarea').setValue('现场证据与结论不一致')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(apiMock.post.mock.calls[0][1]).toEqual({ confirmed: false, edits: {}, note: '现场证据与结论不一致' })
  })

  it('submits typed category, severity and conclusion edits', async () => {
    const wrapper = panel()
    await wrapper.findAll('input[type=radio]')[2].setValue(true)
    const inputs = wrapper.findAll('.review-field input')
    await inputs[0].setValue('消防器材失效')
    await wrapper.findAll('textarea')[0].setValue('人工确认灭火器失效，限期更换')
    await wrapper.findAll('textarea')[1].setValue('核对设备日期后修订')
    const vm = wrapper.vm as unknown as { level: number }
    vm.level = 2
    apiMock.post.mockResolvedValueOnce({ data: { ...assessment(), confirmed: true, status: 'confirmed' } })
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(apiMock.post.mock.calls[0][1]).toEqual({ confirmed: true, note: '核对设备日期后修订', edits: {
      hazard_category: '消防器材失效', risk_level: 2, conclusion: '人工确认灭火器失效，限期更换',
    } })
  })

  it.each([403, 409, 422, 500])('keeps edits and shows HTTP %s errors without reporting success', async (status) => {
    const wrapper = panel()
    await wrapper.get('textarea').setValue('保留我的意见')
    apiMock.post.mockRejectedValueOnce({ response: { status, data: { detail: status === 422
      ? [{ loc: ['body', 'edits'], msg: '字段不合法' }] : '保存被拒绝，请刷新核对' } } })
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.emitted('updated')).toBeUndefined()
    expect(wrapper.get('textarea').element.value).toBe('保留我的意见')
    expect(wrapper.get('[role=alert]').text()).toContain(status === 422 ? '字段不合法' : '保存被拒绝')
  })

  it('prevents rapid double submissions at component and store boundaries', async () => {
    let finish!: (value: { data: Assessment }) => void
    apiMock.post.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    const wrapper = panel()
    await wrapper.get('form').trigger('submit')
    await wrapper.get('form').trigger('submit')
    await expect(useAssessmentStore().confirm(assessment().id, { confirmed: true, edits: {} })).rejects.toThrow('正在保存')
    expect(apiMock.post).toHaveBeenCalledTimes(1)
    finish({ data: assessment() })
    await flushPromises()
  })

  it('does not apply a late response to a different record', async () => {
    let finish!: (value: { data: Assessment }) => void
    apiMock.post.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    const wrapper = panel()
    await wrapper.get('form').trigger('submit')
    await wrapper.setProps({ assessment: { ...assessment(), id: 'another-record' } })
    finish({ data: assessment() })
    await flushPromises()
    expect(wrapper.emitted('updated')).toBeUndefined()
  })

  it.each(['inspector', 'unknown'])('hides submit controls for %s', (value) => {
    role(value)
    const wrapper = panel()
    expect(wrapper.find('form').exists()).toBe(false)
    expect(wrapper.text()).toContain('请复核员或管理员处理')
  })

  it.each(['pending', 'failed', 'needs_more_info', 'confirmed'] as const)('cannot review status %s', (status) => {
    expect(panel({ ...assessment(), status, confirmed: status === 'confirmed' }).find('form').exists()).toBe(false)
  })

  it('shows actual AI snapshots, authenticated reviewer and before/after audit values', () => {
    const item = assessment()
    item.confirmed = true
    item.status = 'confirmed'
    item.human_review = { need_human_review: false, triggers: {}, review_reasons: [],
      ai_original: { available: true, hazard_category: '原 AI 类别', risk_level: 1, conclusion: '原 AI 建议' },
      history: [{ confirmed: true, reviewer: '真实复核员', note: '核对后更正',
        before: { hazard_category: '原 AI 类别', risk_level: 1 }, after: { hazard_category: '最终人工类别', risk_level: 2 } }] }
    const wrapper = panel(item)
    expect(wrapper.text()).toContain('原 AI 建议')
    expect(wrapper.text()).toContain('真实复核员')
    expect(wrapper.text()).toContain('最终人工类别')
    expect(wrapper.text()).toContain('不会重新计算原始风险分数')
  })

  it('does not invent an AI snapshot for a legacy review', () => {
    const item = assessment()
    item.human_review = { need_human_review: true, triggers: {}, review_reasons: [],
      ai_original: { available: false, reason: '历史快照缺失' }, resolution: { confirmed: false, reviewer: '旧复核员' } }
    expect(panel(item).text()).toContain('历史快照缺失')
  })

  it('hides rectification verification and closing from inspectors', () => {
    role('inspector')
    const wrapper = mount(RectificationPanel, { props: { assessment: { ...assessment(), rectification_status: 'verified' } },
      global: { plugins: [ElementPlus], stubs: { ElIcon: true, Plus: true, EditPen: true, RefreshRight: true } } })
    wrappers.push(wrapper)
    expect(wrapper.text()).not.toContain('关闭工单')
    expect(wrapper.text()).not.toContain('退回整改')
  })

  it('returns readable validation errors', () => {
    expect(extractError({ response: { data: { detail: [{ msg: '结论不能为空' }, { msg: '等级必须为整数' }] } } }))
      .toBe('结论不能为空；等级必须为整数')
  })
})
