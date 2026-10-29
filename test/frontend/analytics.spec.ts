import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { apiMock } = vi.hoisted(() => ({ apiMock: { get: vi.fn(), post: vi.fn() } }))
vi.mock('../../frontend/src/api/client', () => ({
  api: apiMock, getStoredToken: () => null, setStoredToken: () => undefined,
}))

import AnalyticsView from '../../frontend/src/views/AnalyticsView.vue'
import type { AnalyticsOptions, AnalyticsOverview, Benchmarks, TrendReport } from '../../frontend/src/types'

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
const trend: TrendReport = {
  as_of: '2026-09',
  rule: { version: 'trend-rule-v1', baseline_months: 6, min_latest: 5, ratio_threshold: 2, min_window_records: 10 },
  backtest: { months_evaluated: 1, triggered: 1, followed: 0, sample_size: 11,
    note: '历史触发回放，不是预测准确率。' },
  sufficiency: { supported: true, reason: '', categories_sufficient: 1, categories_evaluated: 1 },
  evaluations: [{ category: '电气线路隐患', observed: 5, baseline: 1, sample_size: 11,
    sufficient: true, triggered: true, reason: '' }],
  alerts: [{
    id: 'alert-1', rule_version: 'trend-rule-v1', scope_type: 'category', scope_value: '电气线路隐患',
    month: '2026-09', observed: 5, baseline: 1, ratio_threshold: 2, sample_size: 11,
    explanation: '2026-09「电气线路隐患」已确认 5 条，前 6 个月月均 1.0 条，达到 2 倍阈值；评估窗口样本 11 条。',
    status: 'open', created_at: '2026-10-01T00:00:00Z',
  }],
  false_positive_count: 0,
}
const insufficientTrend: TrendReport = {
  ...trend,
  sufficiency: { supported: false, reason: '历史资料不足：每个类别近 7 个月需至少 10 条已确认记录',
    categories_sufficient: 0, categories_evaluated: 1 },
  evaluations: [{ category: '电气线路隐患', observed: 2, baseline: 0, sample_size: 2,
    sufficient: false, triggered: false, reason: '近 7 个月已确认记录仅 2 条，少于 10 条' }],
  alerts: [],
  backtest: { months_evaluated: 0, triggered: 0, followed: 0, sample_size: 2, note: '历史触发回放，不是预测准确率。' },
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

function mockApi(trendData: TrendReport = trend) {
  apiMock.get.mockImplementation(async (url: string) => {
    if (url === '/analytics/options') return { data: options }
    if (url === '/analytics/overview') return { data: overview }
    if (url === '/analytics/benchmarks') return { data: benchmarks }
    if (url === '/analytics/trend-alerts') return { data: structuredClone(trendData) }
    throw new Error(`unexpected ${url}`)
  })
}

beforeEach(() => {
  vi.resetAllMocks()
  setActivePinia(createPinia())
  mockApi()
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

  it('renders explainable trend alerts and records a false-positive decision', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('规则 trend-rule-v1')
    expect(wrapper.text()).toContain('回测：评估 1 个月')
    expect(wrapper.text()).toContain('误报记录 0 条')
    expect(wrapper.text()).toContain('本期 5 条')
    expect(wrapper.text()).toContain('样本 11 条')
    expect(wrapper.text()).toContain('待处理')
    await wrapper.get('[aria-label="趋势处理备注"]').setValue('现场核查为集中排查')
    apiMock.post.mockResolvedValueOnce({ data: {
      ...trend.alerts[0], status: 'false_positive', note: '现场核查为集中排查',
    } })
    await wrapper.findAll('button').find(button => button.text() === '标记误报')!.trigger('click')
    await flushPromises()
    expect(apiMock.post).toHaveBeenCalledWith('/analytics/trend-alerts/alert-1', {
      status: 'false_positive', note: '现场核查为集中排查',
    })
    expect(wrapper.text()).toContain('误报记录 1 条')
  })

  it('refreshes the latest complete month and shows insufficient-history guidance', async () => {
    mockApi(insufficientTrend)
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('历史资料不足')
    expect(wrapper.text()).toContain('当前没有触发规则的趋势提示')
    apiMock.post.mockResolvedValueOnce({ data: structuredClone(trend) })
    await wrapper.findAll('button').find(button => button.text() === '评估最新完整月份')!.trigger('click')
    await flushPromises()
    expect(apiMock.post).toHaveBeenCalledWith('/analytics/trend-alerts/refresh')
    expect(wrapper.text()).toContain('待处理')
  })
})
