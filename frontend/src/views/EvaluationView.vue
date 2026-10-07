<template>
  <section class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">评测总览</h1>
        <p class="page-subtitle">数据来自正式评测产物，不展示推算结果。</p>
      </div>
      <el-button :loading="loading" @click="load">
        <el-icon><Refresh /></el-icon>
        刷新
      </el-button>
    </div>

    <el-alert
      v-if="errorMessage"
      :title="errorMessage"
      type="warning"
      :closable="false"
      show-icon
      class="error-alert"
    />

    <template v-if="report">
      <div class="meta-strip">
        <el-tag :type="modeTag.type">{{ modeTag.label }}</el-tag>
        <el-tag v-if="report.dataset_version" type="info">数据集 {{ report.dataset_version }}</el-tag>
        <el-tag v-if="report.dataset_overview" type="info">
          {{ report.dataset_overview.case_count }} 个案例
        </el-tag>
      </div>

      <el-tabs v-model="activeTab" class="eval-tabs">
        <el-tab-pane label="总览" name="overview">
          <div class="metric-grid">
            <div class="metric-cell">
              <span class="metric-value">{{ fmtRate(m.category_accuracy) }}</span>
              <span class="metric-label">类别准确率</span>
            </div>
            <div class="metric-cell">
              <span class="metric-value">{{ fmtRate(m.level_accuracy) }}</span>
              <span class="metric-label">等级准确率</span>
            </div>
            <div class="metric-cell">
              <span class="metric-value">{{ fmt(m.severity_mae) }}</span>
              <span class="metric-label">Severity MAE</span>
            </div>
            <div class="metric-cell">
              <span class="metric-value">{{ fmtRate(m.level_accuracy_tolerance1) }}</span>
              <span class="metric-label">±1 容差</span>
            </div>
            <div class="metric-cell">
              <span class="metric-value">{{ fmtRate(m.evidence_support_rate) }}</span>
              <span class="metric-label">证据支持率</span>
            </div>
            <div class="metric-cell">
              <span class="metric-value">{{ fmtRate(m.unsupported_claim_rate) }}</span>
              <span class="metric-label">无依据结论率</span>
            </div>
            <div class="metric-cell">
              <span class="metric-value">{{ fmtRate(m.model_conflict_rate) }}</span>
              <span class="metric-label">模型分歧率</span>
            </div>
            <div class="metric-cell">
              <span class="metric-value">{{ fmtRate(m.human_review_rate) }}</span>
              <span class="metric-label">人工复核率</span>
            </div>
            <div class="metric-cell metric-cell--danger">
              <span class="metric-value">{{ fmtRate(m.unsafe_auto_pass_rate) }}</span>
              <span class="metric-label">Unsafe Auto-Pass</span>
            </div>
          </div>

          <section v-if="report.dataset_overview" class="block">
            <h4 class="block-title">Dataset Overview</h4>
            <dl class="overview-grid">
              <div>
                <dt>来源分布</dt>
                <dd>
                  <span
                    v-for="(count, key) in report.dataset_overview.source_type_counts"
                    :key="key"
                    class="dist-chip"
                  >
                    {{ key }} {{ count }}
                  </span>
                </dd>
              </div>
              <div>
                <dt>类别分布</dt>
                <dd>
                  <span
                    v-for="(count, key) in report.dataset_overview.category_counts"
                    :key="key"
                    class="dist-chip"
                  >
                    {{ key }} {{ count }}
                  </span>
                </dd>
              </div>
              <div>
                <dt>等级分布</dt>
                <dd>
                  <span
                    v-for="(count, key) in report.dataset_overview.severity_counts"
                    :key="key"
                    class="dist-chip"
                  >
                    {{ key }} 级 {{ count }}
                  </span>
                </dd>
              </div>
              <div>
                <dt>样本构成</dt>
                <dd>
                  有隐患 {{ report.dataset_overview.hazard_case_count }}，
                  无隐患 {{ report.dataset_overview.safe_negative_case_count }}，
                  含图片 {{ report.dataset_overview.image_case_count }}
                </dd>
              </div>
            </dl>
            <ul v-if="report.dataset_overview.limitation_notes?.length" class="limitation-list">
              <li v-for="note in report.dataset_overview.limitation_notes" :key="note">{{ note }}</li>
            </ul>
          </section>

          <section class="block">
            <h4 class="block-title">模块表现</h4>
            <el-table
              v-if="report.model_family_performance?.length"
              :data="report.model_family_performance"
              size="small"
            >
              <el-table-column prop="family" label="模型家族" />
              <el-table-column prop="attempts" label="有效样本" width="100" />
              <el-table-column label="类别准确率" width="120">
                <template #default="{ row }">{{ fmt(row.category_accuracy) }}</template>
              </el-table-column>
              <el-table-column label="等级准确率" width="120">
                <template #default="{ row }">{{ fmt(row.level_accuracy) }}</template>
              </el-table-column>
            </el-table>
            <p v-if="report.evidence_stats_summary" class="module-line">
              Evidence：支持 {{ report.evidence_stats_summary.supported_count }} 条，
              不足 {{ report.evidence_stats_summary.insufficient_count }} 条
            </p>
            <p v-if="report.review_and_risk_stats" class="module-line">
              Risk Engine：高风险 {{ report.review_and_risk_stats.high_risk_case_count }} 条，
              建议复核 {{ report.review_and_risk_stats.risk_review_suggestion_count }} 条，
              平均风险分 {{ report.review_and_risk_stats.average_risk_score }}
            </p>
          </section>
        </el-tab-pane>

        <el-tab-pane label="消融对比" name="ablation">
          <section class="block">
            <h4 class="block-title">消融对比（A-F）</h4>
            <p v-if="ablation" class="module-line">
              数据集 {{ ablation.dataset_version }} /
              {{ ablation.case_count }} 个案例 /
              {{ ablation.provider_mode }} 模式 /
              来源 {{ pretty(ablation.partitions || ablation.source_type_counts) }}
            </p>
            <el-table v-if="ablationVariants.length" :data="ablationVariants" size="small">
              <el-table-column prop="label" label="变体" min-width="170" />
              <el-table-column label="模式" width="90">
                <template #default="{ row }">
                  {{ row.mode || ablation?.evaluation_mode || '-' }}
                </template>
              </el-table-column>
              <el-table-column label="类别" width="90">
                <template #default="{ row }">{{ fmt(row.metrics.category_accuracy) }}</template>
              </el-table-column>
              <el-table-column label="等级" width="90">
                <template #default="{ row }">{{ fmt(row.metrics.level_accuracy) }}</template>
              </el-table-column>
              <el-table-column label="MAE" width="90">
                <template #default="{ row }">{{ fmt(row.metrics.severity_mae) }}</template>
              </el-table-column>
              <el-table-column label="条款" width="90">
                <template #default="{ row }">{{ fmt(row.metrics.clause_hit_rate) }}</template>
              </el-table-column>
              <el-table-column label="证据支持" width="100">
                <template #default="{ row }">{{ fmt(row.metrics.evidence_support_rate) }}</template>
              </el-table-column>
              <el-table-column label="复核率" width="90">
                <template #default="{ row }">{{ fmt(row.metrics.human_review_rate) }}</template>
              </el-table-column>
              <el-table-column label="分歧率" width="90">
                <template #default="{ row }">{{ fmt(row.metrics.model_conflict_rate) }}</template>
              </el-table-column>
              <el-table-column label="Unsafe" width="90">
                <template #default="{ row }">{{ fmt(row.metrics.unsafe_auto_pass_rate) }}</template>
              </el-table-column>
            </el-table>
            <el-empty v-else description="还没有消融评测结果" />
          </section>
        </el-tab-pane>

        <el-tab-pane label="错误分析" name="errors">
          <section class="block">
            <h4 class="block-title">错误分析</h4>
            <div v-if="report.error_summary?.counts" class="error-grid">
              <div v-for="(count, key) in report.error_summary.counts" :key="key" class="error-cell">
                <span class="error-count">{{ count }}</span>
                <span class="error-name">{{ errorLabel(key) }}</span>
              </div>
            </div>
          </section>

          <section class="block">
            <h4 class="block-title">失败案例清单</h4>
            <el-table
              v-if="report.error_analysis?.length"
              :data="report.error_analysis"
              size="small"
            >
              <el-table-column prop="case_id" label="案例" min-width="150" />
              <el-table-column prop="expected" label="期望" min-width="150" />
              <el-table-column prop="predicted" label="预测" min-width="150" />
              <el-table-column label="错误类型" min-width="160">
                <template #default="{ row }">
                  <span v-for="flag in row.flags" :key="flag" class="flag-tag">
                    {{ errorLabel(flag) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="原因" min-width="260">
                <template #default="{ row }">
                  <span class="reason-text">{{ joinReasons(row) }}</span>
                </template>
              </el-table-column>
            </el-table>
            <el-empty v-else description="没有需要分析的失败案例" />
          </section>
        </el-tab-pane>
      </el-tabs>
    </template>

    <el-empty
      v-else-if="!errorMessage"
      description="还没有评测报告，先运行 scripts/evaluate.py 和 scripts/ablation.py"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { api } from '../api/client'
import type {
  AblationReport,
  EvaluationMetrics,
  EvaluationReport,
  EvaluationReportsPayload,
} from '../types'

const loading = ref(false)
const errorMessage = ref('')
const payload = ref<EvaluationReportsPayload | null>(null)
const activeTab = ref('overview')

const report = computed<EvaluationReport | null>(() => payload.value?.evaluation_report ?? null)
const ablation = computed<AblationReport | null>(() => payload.value?.ablation_report ?? null)
const ablationVariants = computed(() =>
  Object.entries(ablation.value?.variants || {}).map(([key, item]) => ({ key, ...item })),
)

const m = computed<EvaluationMetrics>(() => {
  const current = report.value
  if (!current) return { total: 0 }
  if (current.metrics && Object.keys(current.metrics).length > 0) {
    return current.metrics
  }
  return current as unknown as EvaluationMetrics
})

const modeTag = computed(() => {
  const mode =
    report.value?.evaluation_mode || payload.value?.ablation_report?.evaluation_mode || 'mock'
  const isMock = mode === 'mock' || mode === 'fallback'
  return { type: isMock ? 'info' : 'success', label: isMock ? 'Mock 模式' : '真实模型模式' }
})

onMounted(load)

async function load() {
  loading.value = true
  errorMessage.value = ''
  try {
    const { data } = await api.get<EvaluationReportsPayload>('/evaluation/reports')
    payload.value = data
  } catch (err) {
    payload.value = null
    errorMessage.value = extractDetail(err) || '评测报告加载失败'
  } finally {
    loading.value = false
  }
}

function fmt(value: number | null | undefined) {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : value.toFixed(4)
  }
  return String(value)
}

function fmtRate(value: number | null | undefined) {
  if (value === null || value === undefined) return '-'
  return `${(value * 100).toFixed(1)}%`
}

function pretty(value: Record<string, number> | undefined) {
  return value ? JSON.stringify(value) : '-'
}

function errorLabel(key: string) {
  const labels: Record<string, string> = {
    false_positive: '误报',
    false_negative: '漏报',
    unsafe_auto_pass: 'Unsafe Auto-Pass',
    model_conflict: '模型冲突',
    evidence_failure: '证据失败',
    severity_error: '等级偏差',
  }
  return labels[key] || key
}

function joinReasons(row: { reasons?: Array<{ type: string; reason: string }> }) {
  return (row.reasons || []).map((item) => `${item.type}: ${item.reason}`).join('；')
}

function extractDetail(err: unknown): string {
  if (typeof err === 'object' && err !== null) {
    const anyErr = err as { response?: { data?: { detail?: string } }; message?: string }
    return anyErr.response?.data?.detail || ''
  }
  return ''
}
</script>

<style scoped>
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--s-3);
  flex-wrap: wrap;
}

.error-alert {
  margin: var(--s-4) 0;
}

.meta-strip {
  display: flex;
  gap: var(--s-2);
  flex-wrap: wrap;
  margin: var(--s-4) 0 var(--s-2);
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--s-1) 0;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}

.metric-cell {
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
  padding: var(--s-3) var(--s-3) var(--s-3) 0;
}

.metric-value {
  font-size: var(--fs-2xl);
  font-weight: 700;
  line-height: 1.1;
  color: var(--text-strong);
  font-variant-numeric: tabular-nums;
}

.metric-label {
  font-size: var(--fs-xs);
  color: var(--muted);
}

.metric-cell--danger .metric-value {
  color: var(--warning);
}

.block {
  padding: var(--s-4) 0;
  border-bottom: 1px solid var(--border);
}

.block:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}

.block-title {
  margin: 0 0 var(--s-3);
  font-size: var(--fs-md);
  font-weight: 700;
  color: var(--text-strong);
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--s-3) var(--s-5);
  margin: 0;
}

.overview-grid dt {
  font-size: var(--fs-xs);
  color: var(--muted);
}

.overview-grid dd {
  margin: var(--s-1) 0 0;
  color: var(--text);
  word-break: break-word;
}

.dist-chip {
  display: inline-block;
  margin: 0 var(--s-1) var(--s-1) 0;
  padding: 2px 8px;
  border-radius: var(--r-pill);
  background: var(--panel-2);
  color: var(--text);
  font-size: var(--fs-xs);
}

.limitation-list {
  margin: var(--s-4) 0 0;
  padding-left: 18px;
  color: var(--warning);
  font-size: var(--fs-sm);
}

.module-line {
  margin: var(--s-2) 0 0;
  color: var(--text);
  font-size: var(--fs-sm);
}

.error-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--s-1) 0;
}

.error-cell {
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
  padding-right: var(--s-3);
}

.error-count {
  font-size: var(--fs-xl);
  font-weight: 700;
  color: var(--text-strong);
  font-variant-numeric: tabular-nums;
}

.error-name {
  font-size: var(--fs-xs);
  color: var(--muted);
}

.flag-tag {
  display: inline-block;
  margin: 0 var(--s-1) var(--s-1) 0;
  padding: 2px 8px;
  border-radius: var(--r-pill);
  background: #fee2e2;
  color: var(--danger);
  font-size: var(--fs-xs);
}

.reason-text {
  color: var(--muted);
  font-size: var(--fs-xs);
}
</style>
