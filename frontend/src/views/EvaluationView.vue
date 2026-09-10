<template>
  <section class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">评测总览</h1>
        <p class="page-subtitle">指标、A-F 对比与错误分析均来自正式评测产物，不展示推算数据</p>
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
        <el-tag v-if="report.provider" type="info">Provider {{ report.provider }}</el-tag>
        <el-tag v-if="report.dataset_overview" type="info">
          {{ report.dataset_overview.case_count }} 案例
        </el-tag>
      </div>

      <div class="metric-grid">
        <div class="metric-cell">
          <div class="metric-value">{{ fmt(m.category_accuracy) }}</div>
          <div class="metric-label">类别准确率</div>
        </div>
        <div class="metric-cell">
          <div class="metric-value">{{ fmt(m.level_accuracy) }}</div>
          <div class="metric-label">等级准确率</div>
        </div>
        <div class="metric-cell">
          <div class="metric-value">{{ fmt(m.severity_mae) }}</div>
          <div class="metric-label">Severity MAE</div>
        </div>
        <div class="metric-cell">
          <div class="metric-value">{{ fmt(m.level_accuracy_tolerance1) }}</div>
          <div class="metric-label">±1 容差</div>
        </div>
        <div class="metric-cell">
          <div class="metric-value">{{ fmt(m.evidence_support_rate) }}</div>
          <div class="metric-label">证据支持率</div>
        </div>
        <div class="metric-cell">
          <div class="metric-value">{{ fmt(m.unsupported_claim_rate) }}</div>
          <div class="metric-label">无依据结论率</div>
        </div>
        <div class="metric-cell">
          <div class="metric-value">{{ fmt(m.model_conflict_rate) }}</div>
          <div class="metric-label">模型分歧率</div>
        </div>
        <div class="metric-cell">
          <div class="metric-value">{{ fmt(m.human_review_rate) }}</div>
          <div class="metric-label">人工复核率</div>
        </div>
        <div class="metric-cell danger">
          <div class="metric-value">{{ fmt(m.unsafe_auto_pass_rate) }}</div>
          <div class="metric-label">Unsafe Auto-Pass</div>
        </div>
      </div>

      <el-card class="block-card">
        <template #header>Dataset Overview</template>
        <div v-if="report.dataset_overview" class="overview-list">
          <p>来源分布：{{ pretty(report.dataset_overview.source_type_counts) }}</p>
          <p>类别分布：{{ pretty(report.dataset_overview.category_counts) }}</p>
          <p>等级分布：{{ pretty(report.dataset_overview.severity_counts) }}</p>
          <p>有隐患样本 {{ report.dataset_overview.hazard_case_count }}，
            无隐患负样本 {{ report.dataset_overview.safe_negative_case_count }}，
            含图片 {{ report.dataset_overview.image_case_count }}</p>
          <ul v-if="report.dataset_overview.limitation_notes?.length" class="limitation-list">
            <li v-for="note in report.dataset_overview.limitation_notes" :key="note">{{ note }}</li>
          </ul>
        </div>
      </el-card>

      <el-card class="block-card">
        <template #header>模块表现</template>
        <el-table v-if="report.model_family_performance?.length" :data="report.model_family_performance" size="small">
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
      </el-card>

      <el-card v-if="ablationVariants.length" class="block-card">
        <template #header>消融对比（A-F）</template>
        <p v-if="ablation" class="module-line">
          数据集 {{ ablation.dataset_version }} /
          {{ ablation.case_count }} 案例 /
          {{ ablation.provider_mode }} 模式 / 来源 {{ pretty(ablation.partitions || ablation.source_type_counts) }}
        </p>
        <el-table :data="ablationVariants" size="small">
          <el-table-column prop="label" label="变体" min-width="170" />
          <el-table-column label="模式" width="90">
            <template #default="{ row }">{{ row.mode || ablation?.evaluation_mode || '-' }}</template>
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
      </el-card>

      <el-card class="block-card">
        <template #header>错误分析</template>
        <el-row v-if="report.error_summary?.counts" :gutter="12" class="error-chips">
          <el-col :span="8" :xs="12" v-for="(count, key) in report.error_summary.counts" :key="key">
            <div class="error-chip">
              <span class="error-chip-name">{{ errorLabel(key) }}</span>
              <span class="error-chip-count">{{ count }}</span>
            </div>
          </el-col>
        </el-row>
      </el-card>

      <el-card class="block-card">
        <template #header>失败案例清单</template>
        <el-table
          v-if="report.error_analysis?.length"
          :data="report.error_analysis"
          size="small"
          empty-text="暂无失败案例"
        >
          <el-table-column prop="case_id" label="案例" min-width="150" />
          <el-table-column prop="expected" label="期望" min-width="160" />
          <el-table-column prop="predicted" label="预测" min-width="160" />
          <el-table-column label="错误类型" min-width="170">
            <template #default="{ row }">
              <span v-for="flag in row.flags" :key="flag" class="flag-tag">{{ flag }}</span>
            </template>
          </el-table-column>
          <el-table-column label="原因" min-width="280">
            <template #default="{ row }">
              <span class="reason-text">{{ joinReasons(row) }}</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>

    <el-card v-else-if="!errorMessage" class="block-card">
      <el-empty description="尚未生成评测报告，请先运行 scripts/evaluate.py 与 scripts/ablation.py" />
    </el-card>
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

const report = computed<EvaluationReport | null>(() => payload.value?.evaluation_report ?? null)
const ablation = computed<AblationReport | null>(() => payload.value?.ablation_report ?? null)
const m = computed<EvaluationMetrics>(() => report.value?.metrics || { total: 0 })
const ablationVariants = computed(() =>
  Object.entries(ablation.value?.variants || {}).map(([key, item]) => ({ key, ...item })),
)

const modeTag = computed(() => {
  const mode = report.value?.evaluation_mode || payload.value?.ablation_report?.evaluation_mode || 'mock'
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
  gap: 12px;
  flex-wrap: wrap;
}

.error-alert {
  margin: 14px 0;
}

.meta-strip {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin: 14px 0;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(128px, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.metric-cell {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 12px;
  min-height: 64px;
}

.metric-cell.danger {
  background: #fff7ed;
  border-color: #fdba74;
}

.metric-value {
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
}

.metric-label {
  margin-top: 4px;
  font-size: 12px;
  color: #64748b;
}

.block-card {
  margin-bottom: 14px;
}

.overview-list p {
  margin: 4px 0;
  color: #334155;
}

.limitation-list {
  margin: 8px 0 0;
  padding-left: 18px;
  color: #92400e;
  font-size: 13px;
}

.module-line {
  color: #334155;
  margin: 6px 0;
}

.error-chips {
  row-gap: 10px;
}

.error-chip {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px 10px;
  background: #f1f5f9;
  height: 36px;
}

.error-chip-name {
  color: #475569;
  font-size: 13px;
}

.error-chip-count {
  font-weight: 700;
  color: #be123c;
}

.flag-tag {
  display: inline-block;
  margin-right: 6px;
  padding: 2px 6px;
  border-radius: 4px;
  background: #fee2e2;
  color: #b91c1c;
  font-size: 12px;
}

.reason-text {
  color: #475569;
  font-size: 12px;
}
</style>
