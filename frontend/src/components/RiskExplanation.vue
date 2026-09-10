<template>
  <div class="risk-explanation">
    <div class="explain-overview">
      <div class="explain-score">
        <div class="explain-score-label">风险分</div>
        <el-progress
          type="dashboard"
          :percentage="score"
          :width="120"
          :stroke-width="10"
          :color="scoreColor"
        />
        <span class="explain-level">{{ levelText }}</span>
      </div>
      <div class="explain-summary">
        <div class="explain-summary-row">
          <span>规则等级</span>
          <el-tag :type="levelTag" effect="light">{{ levelText }}</el-tag>
        </div>
        <div class="explain-summary-row">
          <span>严重度提示（模型）</span>
          <span>{{ severityHintText }}</span>
        </div>
        <div class="explain-summary-row">
          <span>建议人工复核</span>
          <span :class="reviewSuggestion ? 'flag-bad' : 'flag-ok'">
            {{ reviewSuggestion ? '是' : '否' }}
          </span>
        </div>
        <div class="explain-summary-row">
          <span>规则版本</span>
          <span class="rule-version">{{ ruleVersion || '未知' }}</span>
        </div>
      </div>
    </div>

    <div v-if="factorRows.length" class="explain-factors">
      <div class="explain-section-title">因子评分与权重</div>
      <div class="factor-table">
        <div v-for="row in factorRows" :key="row.key" class="factor-table-row">
          <span class="factor-name">{{ row.label }}</span>
          <el-progress
            :percentage="row.score"
            :stroke-width="8"
            class="factor-progress"
          />
          <span class="factor-contribution">
            {{ row.weightText }} × {{ row.score }} = {{ row.contribution }}
          </span>
        </div>
      </div>
    </div>

    <p v-if="formulaText" class="explain-formula">{{ formulaText }}</p>

    <div v-if="triggeredRules.length" class="explain-rules">
      <div class="explain-section-title">触发的规则</div>
      <ul>
        <li v-for="rule in triggeredRules" :key="rule.raw">
          <span class="rule-name">{{ rule.label }}</span>
          <span class="rule-raw">{{ rule.raw }}</span>
        </li>
      </ul>
    </div>

    <div class="explain-evidence">
      <div class="explain-section-title">用于风险计算的证据</div>
      <ul v-if="evidenceUsed.length">
        <li v-for="item in evidenceUsed" :key="item">{{ item }}</li>
      </ul>
      <p v-else class="explain-empty">暂无证据使用记录</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import type { Assessment } from '../types'

const props = defineProps<{
  assessment: Assessment
}>()

const risk = computed(() => props.assessment.risk_result ?? null)
const score = computed(
  () => risk.value?.risk_score ?? props.assessment.risk_score ?? 0,
)
const level = computed(
  () => risk.value?.risk_level ?? props.assessment.risk_label ?? '',
)
const weights = computed(
  () => risk.value?.rule_weights ?? {},
)
const reviewSuggestion = computed(
  () =>
    Boolean(risk.value?.review_suggestion) ||
    Boolean(props.assessment.risk_review_suggestion),
)
const severityHint = computed(() => risk.value?.severity_hint ?? null)
const ruleVersion = computed(
  () => risk.value?.rule_version || props.assessment.risk_rule_version || '',
)
const evidenceUsed = computed(
  () =>
    risk.value?.evidence_used ??
    props.assessment.risk_evidence_used ??
    [],
)

const factorLabels: Record<string, string> = {
  exposure: '人员暴露',
  hazard_source: '危险源',
  consequence: '事故后果',
  violation: '违规程度',
  severity_factor: '模型严重度',
}

const factorRows = computed(() => {
  const factors =
    risk.value?.factor_scores ?? props.assessment.risk_factors ?? {}
  return Object.entries(factors).map(([key, value]) => {
    const weight = weights.value[key] ?? 0
    return {
      key,
      label: factorLabels[key] || key,
      score: value,
      weight,
      weightText: `${Math.round(weight * 100)}%`,
      contribution: Math.round(value * weight),
    }
  })
})

const scoreColor = computed(() => {
  if (score.value >= 70) return '#dc2626'
  if (score.value >= 40) return '#d97706'
  return '#16a34a'
})

const levelText = computed(() => {
  const map: Record<string, string> = {
    low: '低风险',
    medium: '中风险',
    high: '高风险',
  }
  return map[level.value] || level.value || '未评级'
})

const levelTag = computed<'success' | 'warning' | 'danger' | 'info'>(() => {
  if (level.value === 'high') return 'danger'
  if (level.value === 'medium') return 'warning'
  if (level.value === 'low') return 'success'
  return 'info'
})

const severityHintText = computed(() =>
  severityHint.value == null ? '无' : `${severityHint.value}/3`,
)

const formulaText = computed(() => {
  const parts: string[] = []
  const order = [
    'exposure',
    'hazard_source',
    'consequence',
    'violation',
    'severity_factor',
  ]
  for (const key of order) {
    const weight = weights.value[key]
    if (weight === undefined) continue
    const label = factorLabels[key] || key
    parts.push(`${weight.toFixed(2)}×${label}`)
  }
  if (!parts.length) return ''
  return `综合分 = ${parts.join(' + ')}，另加立即危险加分（最多 25 分）`
})

const ruleLabels: Record<string, string> = {
  category_base: '类别基础分',
  danger_keyword: '立即危险关键词',
  exposure_keyword: '人员暴露关键词',
  severity_hint: '模型严重度提示',
  severity_missing: '严重度缺失',
  unknown_category: '未知类别',
}

const triggeredRules = computed(() =>
  (risk.value?.triggered_rules ?? props.assessment.risk_triggered_rules ?? []).map(
    (raw) => {
      const [key] = raw.split(':')
      return {
        raw,
        label: ruleLabels[key] || key || raw,
      }
    },
  ),
)
</script>

<style scoped>
.risk-explanation {
  min-height: 100px;
}

.explain-overview {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.explain-score {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.explain-score-label,
.explain-section-title {
  color: #334155;
  font-size: 13px;
  font-weight: 600;
}

.explain-level {
  color: #475569;
  font-size: 13px;
}

.explain-summary {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 220px;
}

.explain-summary-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  color: #475569;
  font-size: 13px;
}

.rule-version {
  color: #94a3b8;
  font-size: 12px;
}

.flag-ok {
  color: #16a34a;
}

.flag-bad {
  color: #dc2626;
}

.factor-table {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 8px 0 10px;
}

.factor-table-row {
  display: flex;
  align-items: center;
  gap: 12px;
  color: #475569;
  font-size: 12px;
}

.factor-name {
  width: 84px;
  flex: 0 0 auto;
}

.factor-progress {
  flex: 1;
  max-width: 220px;
}

.factor-contribution {
  color: #64748b;
  white-space: nowrap;
}

.explain-formula {
  margin: 0 0 10px;
  padding: 8px 10px;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  border-radius: 6px;
  color: #0c4a6e;
  font-size: 12px;
}

.explain-rules,
.explain-evidence {
  margin-bottom: 10px;
}

.explain-rules ul,
.explain-evidence ul {
  margin: 8px 0 0;
  padding-left: 18px;
  color: #475569;
  font-size: 12px;
}

.explain-rules li,
.explain-evidence li {
  margin-bottom: 4px;
}

.rule-name {
  margin-right: 8px;
  color: #334155;
  font-weight: 600;
}

.rule-raw {
  color: #64748b;
}

.explain-empty {
  margin: 8px 0 0;
  color: #94a3b8;
  font-size: 12px;
}
</style>
