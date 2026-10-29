<template>
  <section class="page analytics-page">
    <div class="page-head">
      <div>
        <h1 class="page-title">管理分析</h1>
        <p class="page-subtitle">仅统计人工已确认记录；数量不代表风险排名。</p>
      </div>
      <el-button :loading="store.loading" @click="refresh">刷新</el-button>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="error-alert" />

    <el-card class="filter-card">
      <form class="filter-grid" @submit.prevent="applyFilters">
        <label>区划
          <select v-model="filters.district" aria-label="区划筛选">
            <option value="">全部</option>
            <option v-for="value in store.options?.districts || []" :key="value" :value="value">{{ value }}</option>
          </select>
        </label>
        <label>类别
          <select v-model="filters.category" aria-label="类别筛选">
            <option value="">全部</option>
            <option v-for="value in store.options?.categories || []" :key="value" :value="value">{{ value }}</option>
          </select>
        </label>
        <label>设施
          <select v-model="filters.facility" aria-label="设施筛选">
            <option value="">全部</option>
            <option v-for="value in store.options?.facilities || []" :key="value" :value="value">{{ value }}</option>
          </select>
        </label>
        <label>场景
          <select v-model="filters.scene" aria-label="场景筛选">
            <option value="">全部</option>
            <option v-for="value in store.options?.scenes || []" :key="value" :value="value">{{ value }}</option>
          </select>
        </label>
        <label>开始月份<input v-model="filters.start" aria-label="开始月份" type="month" /></label>
        <label>结束月份<input v-model="filters.end" aria-label="结束月份" type="month" /></label>
        <el-button native-type="submit" type="primary" :loading="store.loading">应用筛选</el-button>
      </form>
    </el-card>

    <template v-if="store.overview">
      <p class="time-basis">{{ store.overview.notice }}</p>
      <div class="summary-grid">
        <div class="summary-cell">
          <span class="summary-value">{{ store.overview.total }}</span>
          <span class="summary-label">已确认记录</span>
        </div>
        <div class="summary-cell">
          <span class="summary-value">{{ ungradedCount }}</span>
          <span class="summary-label">未分级</span>
        </div>
        <div v-for="row in store.overview.collected" :key="row.value" class="summary-cell">
          <span class="summary-value">{{ row.count }}</span>
          <span class="summary-label">收集到的{{ row.label }}</span>
        </div>
      </div>

      <el-alert
        v-if="simulatedCount"
        :title="`已确认统计含模拟数据 ${simulatedCount} 条，请勿当作真实风险分布`"
        type="warning"
        :closable="false"
        show-icon
        class="simulated-alert"
      />

      <div class="distribution-grid">
        <el-card>
          <h2>风险等级</h2>
          <ul class="bucket-list">
            <li v-for="row in store.overview.by_risk" :key="row.value">
              <span>{{ row.label }}</span><span>{{ row.count }}</span>
            </li>
          </ul>
        </el-card>
        <el-card>
          <h2>按区划</h2>
          <ul v-if="store.overview.by_district.length" class="bucket-list">
            <li v-for="row in store.overview.by_district" :key="row.value">
              <span>{{ row.value }}</span><span>{{ row.count }}</span>
            </li>
          </ul>
          <p v-else class="hint">当前筛选下没有已确认记录。</p>
        </el-card>
        <el-card>
          <h2>按类别</h2>
          <ul v-if="store.overview.by_category.length" class="bucket-list">
            <li v-for="row in store.overview.by_category" :key="row.value">
              <span>{{ row.value }}</span><span>{{ row.count }}</span>
            </li>
          </ul>
          <p v-else class="hint">当前筛选下没有已确认记录。</p>
        </el-card>
      </div>

      <el-card class="section-card">
        <h2>月度趋势</h2>
        <p class="hint">时间口径：事件时间，未填写时使用录入时间；零记录月份仍会列出。</p>
        <ul v-if="store.overview.months.length" class="month-list">
          <li v-for="row in store.overview.months" :key="row.month">
            <span>{{ row.month }}</span>
            <span class="month-count" :class="{ zero: row.count === 0 }">{{ row.count }} 条</span>
          </li>
        </ul>
        <p v-else class="hint">当前筛选下没有已确认记录。</p>
      </el-card>

      <el-card class="section-card">
        <h2>地图</h2>
        <DistributionMap v-if="store.overview.map_points.length" :points="store.overview.map_points" />
        <p v-else class="hint">当前筛选下没有带坐标的已确认记录。</p>
        <p v-if="store.overview.map_truncated" class="hint">地图仅显示前 500 个点位。</p>
        <ul v-if="pointRows.length" class="point-list">
          <li v-for="point in pointRows" :key="point.id">
            <span>{{ point.district || '未填写区划' }} · {{ point.description }}</span>
            <RouterLink :to="`/assessments/${point.id}`">查看记录</RouterLink>
          </li>
        </ul>
        <p v-if="store.overview.map_points.length > pointRows.length" class="hint">
          点位记录仅列出前 {{ pointRows.length }} 条，可按筛选缩小范围。
        </p>
      </el-card>

      <el-card class="section-card">
        <h2>同类整改对标</h2>
        <p class="hint">按设施和/或场景查找其他地点已确认记录中的整改方案与结果；不能据此直接作出处置决定。</p>
        <form class="benchmark-form" @submit.prevent="searchBenchmarks">
          <label>设施
            <select v-model="benchFilters.facility" aria-label="对标设施">
              <option value="">不限</option>
              <option v-for="value in store.options?.facilities || []" :key="value" :value="value">{{ value }}</option>
            </select>
          </label>
          <label>场景
            <select v-model="benchFilters.scene" aria-label="对标场景">
              <option value="">不限</option>
              <option v-for="value in store.options?.scenes || []" :key="value" :value="value">{{ value }}</option>
            </select>
          </label>
          <label>类别
            <select v-model="benchFilters.category" aria-label="对标类别">
              <option value="">不限</option>
              <option v-for="value in store.options?.categories || []" :key="value" :value="value">{{ value }}</option>
            </select>
          </label>
          <el-button native-type="submit" type="primary" :loading="store.benchmarkLoading"
            :disabled="!benchFilters.facility && !benchFilters.scene">
            查询对标
          </el-button>
        </form>
        <p v-if="benchmarkError" class="benchmark-error" role="alert">{{ benchmarkError }}</p>
        <template v-if="store.benchmarks">
          <div class="benchmark-summary">
            <span>样本量 {{ store.benchmarks.sample_size }} 条</span>
            <span>筛选：{{ filterText }}</span>
            <span>来源：{{ sourceText }}</span>
          </div>
          <p class="hint">{{ store.benchmarks.notice }}</p>
          <div v-if="store.benchmarks.items.length" class="table-wrap">
            <table class="benchmark-table">
              <thead>
                <tr>
                  <th>区划</th><th>设施 / 场景</th><th>类别</th><th>整改状态</th>
                  <th>整改说明</th><th>来源</th><th>可比性</th><th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in store.benchmarks.items" :key="item.id">
                  <td>{{ item.district || '未填写' }}</td>
                  <td>{{ [item.facility, item.scene].filter(Boolean).join(' / ') || '未填写' }}</td>
                  <td>{{ item.hazard_category || '未填写' }}</td>
                  <td>{{ rectStatusLabel(item.rectification_status) }}</td>
                  <td class="note-cell">{{ item.rectification_note || '未填写' }}</td>
                  <td>{{ sourceLabel(item.data_source) }}</td>
                  <td>{{ item.comparable }}</td>
                  <td><RouterLink :to="`/assessments/${item.id}`">查看</RouterLink></td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="hint">没有匹配的已整改记录，不能据此推断处置方案。</p>
          <p v-if="store.benchmarks.truncated" class="hint">仅显示前 {{ store.benchmarks.returned }} 条。</p>
        </template>
      </el-card>

      <el-card class="section-card">
        <h2>历史趋势提示</h2>
        <template v-if="trend">
          <p class="hint">
            规则 {{ trend.rule.version }}：前 {{ trend.rule.baseline_months }} 个月月均的
            {{ trend.rule.ratio_threshold }} 倍，且当月不少于 {{ trend.rule.min_latest }} 条；
            评估窗口样本不少于 {{ trend.rule.min_window_records }} 条。仅使用非模拟的人工已确认记录。
          </p>
          <div class="benchmark-summary">
            <span>评估月份 {{ trend.as_of }}</span>
            <span>
              回测：评估 {{ trend.backtest.months_evaluated }} 个月，触发 {{ trend.backtest.triggered }} 次，
              次月仍高 {{ trend.backtest.followed }} 次，样本 {{ trend.backtest.sample_size }} 条
            </span>
            <span>误报记录 {{ trend.false_positive_count }} 条</span>
          </div>
          <p class="hint">{{ trend.backtest.note }}</p>
          <el-alert
            v-if="!trend.sufficiency.supported"
            :title="trend.sufficiency.reason"
            type="info"
            :closable="false"
            show-icon
            class="trend-alert"
          />
          <div class="trend-actions">
            <el-button type="primary" plain :loading="updates.trendBusy" @click="refreshTrend">
              评估最新完整月份
            </el-button>
            <label class="trend-note">处理备注（可选）
              <input v-model="trendNote" aria-label="趋势处理备注" :maxlength="1000" placeholder="例如：现场核查为集中排查" />
            </label>
          </div>
          <div v-if="trend.alerts.length" class="table-wrap">
            <table class="benchmark-table">
              <thead>
                <tr>
                  <th>月份</th><th>类别</th><th>本期</th><th>基线月均</th><th>样本量</th>
                  <th>状态</th><th>说明</th><th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="alert in trend.alerts" :key="alert.id">
                  <td>{{ alert.month }}</td>
                  <td>{{ alert.scope_value }}</td>
                  <td>{{ alert.observed }} 条</td>
                  <td>{{ alert.baseline.toFixed(1) }} 条</td>
                  <td>{{ alert.sample_size }} 条</td>
                  <td>{{ trendStatus(alert.status) }}</td>
                  <td class="note-cell">
                    {{ alert.explanation }}
                    <p v-if="alert.note" class="hint">处理备注：{{ alert.note }}</p>
                  </td>
                  <td class="trend-actions-cell">
                    <el-button v-if="alert.status !== 'acknowledged'" link type="primary"
                      @click="reviewTrend(alert.id, 'acknowledged')">确认关注</el-button>
                    <el-button v-if="alert.status !== 'false_positive'" link type="danger"
                      @click="reviewTrend(alert.id, 'false_positive')">标记误报</el-button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="hint">当前没有触发规则的趋势提示。</p>
          <details v-if="trend.evaluations.length" class="trend-evaluations">
            <summary>各类别评估明细</summary>
            <ul>
              <li v-for="row in trend.evaluations" :key="row.category">
                <span>{{ row.category }}：本期 {{ row.observed }} 条 / 基线月均 {{ row.baseline.toFixed(1) }} / 样本 {{ row.sample_size }}</span>
                <span>{{ row.reason || (row.triggered ? '触发规则' : '未触发') }}</span>
              </li>
            </ul>
          </details>
          <p v-if="trendError" class="benchmark-error" role="alert">{{ trendError }}</p>
        </template>
        <p v-else class="hint">正在加载趋势提示…</p>
      </el-card>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import DistributionMap from '../components/DistributionMap.vue'
import { rectStatusLabel } from '../constants/rectification'
import { useAnalyticsStore, type BenchmarkFilters } from '../stores/analytics'
import type { AnalyticsFilters } from '../stores/analytics'
import { useUpdatesStore } from '../stores/updates'
import { extractError } from '../utils/errors'

const SOURCE_LABELS: Record<string, string> = {
  report: '现场上报', public_case: '公开案例', simulated: '模拟数据', unknown: '未标注',
}
const store = useAnalyticsStore()
const updates = useUpdatesStore()
const filters = reactive<AnalyticsFilters>({
  district: '', category: '', facility: '', scene: '', start: '', end: '',
})
const benchFilters = reactive<BenchmarkFilters>({ facility: '', scene: '', category: '' })
const error = ref('')
const benchmarkError = ref('')
const trendError = ref('')
const trendNote = ref('')
const trend = computed(() => updates.trend)
const pointRows = computed(() => store.overview?.map_points.slice(0, 50) || [])
const ungradedCount = computed(() =>
  store.overview?.by_risk.find(row => row.value === 'ungraded')?.count || 0)
const simulatedCount = computed(() =>
  store.overview?.by_source.find(row => row.value === 'simulated')?.count || 0)
const filterText = computed(() => {
  const current = store.benchmarks?.filters
  if (!current) return '未查询'
  const parts = [
    current.facility ? `设施=${current.facility}` : '',
    current.scene ? `场景=${current.scene}` : '',
    current.category ? `类别=${current.category}` : '',
  ].filter(Boolean)
  return parts.length ? parts.join(' · ') : '未限定'
})
const sourceText = computed(() => {
  const sources = store.benchmarks?.sources || []
  return sources.length ? sources.map(row => `${row.label || row.value} ${row.count} 条`).join('、') : '无'
})

onMounted(refresh)

async function refresh() {
  error.value = ''
  try {
    await store.loadOptions()
    await applyFilters()
  } catch (err) {
    error.value = extractError(err)
  }
  await loadTrend()
}

async function loadTrend() {
  trendError.value = ''
  try {
    await updates.loadTrend()
  } catch (err) {
    trendError.value = extractError(err)
  }
}

async function refreshTrend() {
  trendError.value = ''
  try {
    await updates.refreshTrend()
  } catch (err) {
    trendError.value = extractError(err)
  }
}

async function reviewTrend(id: string, status: 'acknowledged' | 'false_positive') {
  trendError.value = ''
  try {
    await updates.reviewTrend(id, status, trendNote.value.trim())
    trendNote.value = ''
  } catch (err) {
    trendError.value = extractError(err)
  }
}

function trendStatus(status: string) {
  return { open: '待处理', acknowledged: '已关注', false_positive: '误报' }[status] || status
}

async function applyFilters() {
  error.value = ''
  if (filters.start && filters.end && filters.start > filters.end) {
    error.value = '开始月份不能晚于结束月份'
    return
  }
  try {
    await store.loadOverview(filters)
  } catch (err) {
    error.value = extractError(err)
  }
}

async function searchBenchmarks() {
  benchmarkError.value = ''
  if (!benchFilters.facility && !benchFilters.scene) {
    benchmarkError.value = '请至少选择设施或场景'
    return
  }
  try {
    await store.loadBenchmarks(benchFilters)
  } catch (err) {
    benchmarkError.value = extractError(err)
  }
}

function sourceLabel(value?: string | null) {
  return SOURCE_LABELS[value || 'unknown'] || value || '未标注'
}
</script>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s-4);
  margin-bottom: var(--s-4);
}

.error-alert {
  margin-bottom: var(--s-4);
}

.filter-grid,
.benchmark-form {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 150px), 1fr));
  gap: var(--s-3);
  align-items: end;
}

.filter-grid label,
.benchmark-form label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.filter-grid select,
.filter-grid input,
.benchmark-form select {
  box-sizing: border-box;
  width: 100%;
  min-height: 36px;
  font: inherit;
  color: var(--text);
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--r-control);
  padding: 6px 8px;
}

.time-basis {
  margin: var(--s-3) 0;
  color: var(--muted);
  font-size: var(--fs-sm);
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 160px), 1fr));
  gap: var(--s-3);
  margin-bottom: var(--s-3);
}

.summary-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--s-3);
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--r-card);
}

.summary-value {
  font-size: var(--fs-2xl);
  font-weight: 700;
  color: var(--text-strong);
}

.summary-label {
  color: var(--muted);
  font-size: var(--fs-sm);
}

.simulated-alert {
  margin-bottom: var(--s-3);
}

.distribution-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr));
  gap: var(--s-3);
  margin-bottom: var(--s-3);
}

h2 {
  margin: 0 0 var(--s-3);
  font-size: var(--fs-md);
}

.bucket-list,
.month-list,
.point-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.bucket-list li,
.month-list li,
.point-list li {
  display: flex;
  justify-content: space-between;
  gap: var(--s-3);
  padding: var(--s-2) 0;
  border-bottom: 1px solid var(--border);
}

.bucket-list li:last-child,
.month-list li:last-child,
.point-list li:last-child {
  border-bottom: 0;
}

.month-count.zero {
  color: var(--muted);
}

.point-list {
  margin-top: var(--s-3);
}

.point-list span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.section-card {
  margin-top: var(--s-3);
}

.hint {
  margin: var(--s-2) 0;
  color: var(--muted);
  font-size: var(--fs-sm);
}

.benchmark-summary {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s-3);
  margin: var(--s-3) 0;
  color: var(--text-strong);
  font-size: var(--fs-sm);
}

.table-wrap {
  overflow-x: auto;
  margin-top: var(--s-2);
}

.benchmark-table {
  width: 100%;
  min-width: 760px;
  border-collapse: collapse;
  font-size: var(--fs-sm);
}

.benchmark-table th,
.benchmark-table td {
  padding: 8px;
  text-align: left;
  vertical-align: top;
  border-bottom: 1px solid var(--border);
}

.benchmark-table th {
  color: var(--muted);
  font-weight: 600;
  white-space: nowrap;
}

.note-cell {
  max-width: 260px;
  overflow-wrap: anywhere;
}

.benchmark-error {
  color: var(--danger, #d14343);
}

.trend-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: end;
  gap: var(--s-3);
  margin: var(--s-3) 0;
}

.trend-note {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: min(100%, 260px);
  color: var(--muted);
  font-size: var(--fs-sm);
}

.trend-note input {
  box-sizing: border-box;
  width: 100%;
  min-height: 36px;
  font: inherit;
  color: var(--text);
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--r-control);
  padding: 6px 8px;
}

.trend-alert {
  margin: var(--s-2) 0;
}

.trend-actions-cell {
  white-space: nowrap;
}

.trend-evaluations {
  margin-top: var(--s-3);
}

.trend-evaluations summary {
  cursor: pointer;
  color: var(--text-strong);
}

.trend-evaluations ul {
  margin: var(--s-2) 0 0;
  padding: 0;
  list-style: none;
}

.trend-evaluations li {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--s-2);
  padding: var(--s-2) 0;
  border-bottom: 1px solid var(--border);
}

a {
  color: var(--brand);
}
</style>
