import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { apiMock, routerPush } = vi.hoisted(() => ({ apiMock: { post: vi.fn(), get: vi.fn() }, routerPush: vi.fn() }))
vi.mock('../../frontend/src/api/client', () => ({
  api: apiMock, getStoredToken: () => null, setStoredToken: () => undefined,
}))
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routerPush }),
  RouterLink: { props: ['to'], template: '<a><slot /></a>' },
}))

import AssessmentResult from '../../frontend/src/components/AssessmentResult.vue'
import { useAuthStore } from '../../frontend/src/stores/auth'
import type { Assessment } from '../../frontend/src/types'
import HistoryView from '../../frontend/src/views/HistoryView.vue'
import HomeView from '../../frontend/src/views/HomeView.vue'
import { makeAssessment } from './fixtures/assessment'

const completed = (id = 'assessment-m3'): Assessment => ({ ...makeAssessment(), id, status: 'completed' })
const wrappers: ReturnType<typeof mount>[] = []

function mountHome() {
  const wrapper = shallowMount(HomeView, { global: {
    directives: { loading: () => undefined },
    stubs: {
      ElRadioGroup: { template: '<div><slot /></div>' },
      ElRadioButton: { template: '<span><slot /></span>' },
      ElCard: { template: '<section><slot /></section>' },
      ElButton: { props: ['disabled'], template: '<button :disabled="disabled"><slot /></button>' },
      ElIcon: { template: '<span><slot /></span>' },
      ElUpload: true, ElInput: true, ElAlert: true, Plus: true, UploadFilled: true, RouterLink: true,
      JobProgress: true, AssessmentResult: true,
    },
  } })
  wrappers.push(wrapper)
  return wrapper
}

beforeEach(() => {
  vi.resetAllMocks()
  sessionStorage.clear()
  setActivePinia(createPinia())
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); document.body.innerHTML = '' })

describe('M3 location entry and import', () => {
  it('submits manual location, data source and event time without requiring coordinates', async () => {
    apiMock.post.mockResolvedValueOnce({ data: completed() })
    const wrapper = mountHome()
    const inputs = wrapper.findAllComponents({ name: 'ElInput' })
    inputs[0].vm.$emit('update:modelValue', '楼道堆物影响疏散')
    inputs[1].vm.$emit('update:modelValue', '示例路 3 号 2 单元')
    inputs[2].vm.$emit('update:modelValue', '示例区')
    inputs[3].vm.$emit('update:modelValue', '居民楼')
    inputs[4].vm.$emit('update:modelValue', '楼道')
    await wrapper.get('input[type="datetime-local"]').setValue('2026-10-20T09:30')
    await wrapper.get('select[aria-label="数据来源"]').setValue('simulated')
    await flushPromises()
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    const form = apiMock.post.mock.calls[0][1] as FormData
    expect(form.get('address')).toBe('示例路 3 号 2 单元')
    expect(form.get('district')).toBe('示例区')
    expect(form.get('facility')).toBe('居民楼')
    expect(form.get('scene')).toBe('楼道')
    expect(form.get('data_source')).toBe('simulated')
    expect(new Date(String(form.get('event_time'))).getTime()).toBe(new Date('2026-10-20T09:30').getTime())
    expect(form.get('latitude')).toBeNull()
    expect(form.get('coordinate_system')).toBeNull()
  })

  it('sends coordinates only as a complete pair with an explicit coordinate system', async () => {
    apiMock.post.mockResolvedValueOnce({ data: completed() })
    const wrapper = mountHome()
    wrapper.findAllComponents({ name: 'ElInput' })[0].vm.$emit('update:modelValue', '现场描述')
    await wrapper.get('input[aria-label="纬度"]').setValue('30.123456')
    expect(wrapper.text()).toContain('经纬度须同时填写或同时留空')
    await wrapper.get('input[aria-label="经度"]').setValue('120.654321')
    await wrapper.get('select[aria-label="坐标系"]').setValue('gcj02')
    await flushPromises()
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    const form = apiMock.post.mock.calls[0][1] as FormData
    expect(form.get('latitude')).toBe('30.123456')
    expect(form.get('longitude')).toBe('120.654321')
    expect(form.get('coordinate_system')).toBe('gcj02')
    expect(form.get('address')).toBeNull()
  })

  it('shows imported records with source, event time and precision, never as a judgement', () => {
    const imported: Assessment = {
      ...makeAssessment(), id: 'import-1', status: 'imported', record_mode: 'imported', confirmed: false,
      description: '公开案例：市场通道堆物', data_source: 'public_case', address: '示例路 9 号',
      district: '示例区', facility: '市场', scene: '通道', latitude: 30.2, longitude: 120.2,
      coordinate_source: 'import', coordinate_system: 'wgs84', location_precision: 'coordinate',
      event_time: '2026-10-18T10:00:00Z', source_ref: 'PUBLIC-1', import_batch_id: 'batch-1',
    }
    const wrapper = shallowMount(AssessmentResult, { props: { assessment: imported }, global: {
      directives: { loading: () => undefined },
      stubs: {
        ClassificationPanel: true, HumanReviewPanel: true, EvidenceChain: true, RectificationPanel: true,
        DisagreementViz: true, HazardOverlay: true, LegalEvidence: true, ModelComparison: true,
        RiskExplanation: true,
      },
    } })
    wrappers.push(wrapper)
    expect(wrapper.text()).toContain('公开案例')
    expect(wrapper.text()).toContain('坐标级')
    expect(wrapper.text()).toContain('WGS84')
    expect(wrapper.text()).toContain('导入')
    expect(wrapper.text()).toContain('batch-1')
    expect(wrapper.text()).toContain('PUBLIC-1')
    expect(wrapper.text()).toContain('未做 AI 研判')
    expect(wrapper.text()).toContain('录入时间')
    expect(wrapper.text()).toContain('事件时间')
  })

  it('imports a JSON batch and lists duplicate and failed rows', async () => {
    const auth = useAuthStore()
    auth.authMode = 'none'
    apiMock.get.mockResolvedValue({ data: [] })
    apiMock.post.mockResolvedValueOnce({ data: {
      batch_id: 'batch-9', imported: 1, duplicates: [2],
      failures: [{ row: 3, source_ref: 'BAD-3', reason: 'data_source: Input should be one of...' }],
    } })
    const wrapper = mount(HistoryView, { global: {
      plugins: [ElementPlus],
      stubs: { RouterLink: true },
    } })
    wrappers.push(wrapper)
    await flushPromises()
    const file = new File([JSON.stringify([
      { source_ref: 'PUBLIC-1', description: '案例一', data_source: 'public_case' },
      { source_ref: 'PUBLIC-1', description: '重复', data_source: 'public_case' },
      { source_ref: 'BAD-3', description: '错误', data_source: 'guess' },
    ])], 'cases.json', { type: 'application/json' })
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [file] })
    await input.trigger('change')
    await flushPromises()
    expect(wrapper.text()).toContain('cases.json（3 条）')
    const button = wrapper.findAll('button').find(item => item.text().includes('导入 3 条'))
    await button!.trigger('click')
    await flushPromises()
    expect(apiMock.post).toHaveBeenCalledWith('/assessments/import', { rows: expect.any(Array) })
    expect(wrapper.text()).toContain('成功 1 条')
    expect(wrapper.text()).toContain('重复 1 条')
    expect(wrapper.text()).toContain('第 3 行（BAD-3）')
    expect(wrapper.text()).toContain('batch-9')
  })
})
