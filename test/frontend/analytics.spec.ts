import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { apiMock } = vi.hoisted(() => ({ apiMock: { get: vi.fn(), post: vi.fn() } }))
vi.mock('../../frontend/src/api/client', () => ({
  api: apiMock, getStoredToken: () => null, setStoredToken: () => undefined,
}))

import AnalyticsView from '../../frontend/src/views/AnalyticsView.vue'
import type { AnalyticsOptions, AnalyticsOverview, Benchmarks } from '../../frontend/src/types'

const options: AnalyticsOptions = {
  districts: ['甲区', '乙区'], categories: ['占用疏散通道', '消防器材失效'],
  facilities: ['居民楼', '市场'], scenes: ['楼道', '仓库'],
}
const overview: AnalyticsOverview = {
  time_basis: 'event_time_else_created_at',
  total: 4,
  by_district: [{ value: '甲区', count: 3 }, { value: '乙区', count: 1 }],
  by_category: [{ value: '占用疏散通道', count: 4 }],
  by_risk: [
    { value: '1', label: '一级（高）', count: 2 }, { value: '2', label: '二级（中）', count: 1 },
    { value: '3', label: '三级（较低）', count: 0 }, { value: 'ungraded', label: '未分级', count: 1 },
  ],
  by_source: [{ value: 'report', label: '现场上报', count: 3 }, { value: 'simulated', label: '模拟数据', count: 1 }],
  months: [{ month: '2026-01', count: 2 }, { month: '2026-02', count: 0 }, { month: '2026-03', count: 2 }],
  map_points: [{
    id: 'map-1', description: '楼道堆物', district: '甲区', facility: '居民楼', scene: '楼道',
    risk_level: 1, latitude: 30.1, longitude: 120.1, coordinate_system: 'gcj02',
    map_latitude: 30.098, map_longitude: 120.096, created_at: '2026-01-10T00:00:00Z',
  }],
  map_truncated: false,
  collected: [{ value: 'public_case', label: '公开案例', count: 2 }],
  notice: '统计仅含人工已确认记录；数量不代表风险排名。',
}
const benchmarks: Benchmarks = {
  filters: { facility: '居民楼', scene: '楼道', category: null },
  sample_size: 2,
  returned: 2,
  truncated: false,
  sources: [{ value: 'report', label: '现场上报', count: 2 }],
  items: [
    { id: 'bench-1', description: '案例一', district: '甲区', facility: '居民楼', scene: '楼道',
      hazard_category: '占用疏散通道', rectification_status: 'verified', rectification_note: '清理并复检',
      data_source: 'report', match: 'both', comparable: '设施与场景一致' },
    { id: 'bench-2', description: '案例二', district: '乙区', facility: '居民楼', scene: '仓库',
      hazard_category: '占用疏散通道', rectification_status: 'rectifying', rectification_note: '整改中',
      data_source: 'report', match: 'facility', comparable: '仅设施一致' },
  ],
  notice: '对标仅汇总已确认记录；不能据此直接作出处置决定。',
}

const wrappers: ReturnType<typeof mount>[] = []

function mountPage() {
  const wrapper = mount(AnalyticsView, { global: {
    plugins: [ElementPlus],
    stubs: { RouterLink: RouterLinkStub, DistributionMap: { props: ['points'], template: '<div class="map-stub" />' } },
  } })
  wrappers.push(wrapper)
  return wrapper
}

beforeEach(() => {
  vi.resetAllMocks()
  setActivePinia(createPinia())
  apiMock.get.mockImplementation(async (url: string) => {
    if (url === '/analytics/options') return { data: options }
    if (url === '/analytics/overview') return { data: overview }
    if (url === '/analytics/benchmarks') return { data: benchmarks }
    throw new Error(`unexpected ${url}`)
  })
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); document.body.innerHTML = '' })

describe('M4 management analytics', () => {
  it('shows hand-checkable totals, ungraded bucket and zero months', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('4')
    expect(wrapper.text()).toContain('未分级')
    expect(wrapper.text()).toContain('2026-02')
    const february = wrapper.findAll('.month-list li').find(row => row.text().includes('2026-02'))
    expect(february!.text()).toContain('0 条')
    expect(wrapper.text()).toContain('收集到的公开案例')
    expect(wrapper.text()).toContain('含模拟数据 1 条')
    expect(wrapper.text()).toContain('数量不代表风险排名')
    expect(wrapper.find('.map-stub').exists()).toBe(true)
    const links = wrapper.findAllComponents(RouterLinkStub).map(link => link.props('to'))
    expect(links).toContain('/assessments/map-1')
  })

  it('applies filters and reports the selected scope', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('select[aria-label="区划筛选"]').setValue('甲区')
    await wrapper.findAll('form')[0].trigger('submit')
    await flushPromises()
    const call = apiMock.get.mock.calls.filter(([url]) => url === '/analytics/overview').at(-1)!
    expect(call[1].params).toEqual({ district: '甲区' })
  })

  it('shows benchmark sample size, source, comparability and drill-down link', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('select[aria-label="对标设施"]').setValue('居民楼')
    await wrapper.findAll('form')[1].trigger('submit')
    await flushPromises()
    const call = apiMock.get.mock.calls.find(([url]) => url === '/analytics/benchmarks')!
    expect(call[1].params).toEqual({ facility: '居民楼' })
    expect(wrapper.text()).toContain('样本量 2 条')
    expect(wrapper.text()).toContain('设施=居民楼')
    expect(wrapper.text()).toContain('现场上报 2 条')
    expect(wrapper.text()).toContain('设施与场景一致')
    expect(wrapper.text()).toContain('仅设施一致')
    expect(wrapper.text()).toContain('不能据此直接作出处置决定')
    const links = wrapper.findAllComponents(RouterLinkStub).map(link => link.props('to'))
    expect(links).toContain('/assessments/bench-1')
  })

  it('requires a facility or scene before benchmarking and surfaces API errors', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.findAll('form')[1].trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('请至少选择设施或场景')
    expect(apiMock.get.mock.calls.some(([url]) => url === '/analytics/benchmarks')).toBe(false)

    apiMock.get.mockRejectedValueOnce({ response: { data: { detail: '需要角色：reviewer/admin' } } })
    const failed = mountPage()
    await flushPromises()
    expect(failed.text()).toContain('需要角色：reviewer/admin')
  })
})
