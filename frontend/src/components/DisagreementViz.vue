<template>
  <div class="disagreement-viz">
    <template v-if="disagreement">
      <div class="viz-overview">
        <div class="viz-score">
          <div class="viz-score-label">模型一致性</div>
          <el-progress
            type="dashboard"
            :percentage="agreementPercent"
            :width="120"
            :stroke-width="10"
            :color="agreementColor"
          />
          <p v-if="!disagreement.agreement_available" class="viz-score-hint">
            未进行交叉验证
          </p>
        </div>
        <div class="viz-summary">
          <div class="viz-summary-row">
            <span>模式</span>
            <el-tag :type="modeTag" size="small">{{ modeLabel }}</el-tag>
          </div>
          <div class="viz-summary-row">
            <span>类别一致</span>
            <span :class="flagClass(disagreement.category_agreement)">
              {{ booleanText(disagreement.category_agreement) }}
            </span>
          </div>
          <div class="viz-summary-row">
            <span>严重度差</span>
            <span>{{ disagreement.severity_difference ?? '暂无' }}</span>
          </div>
          <div class="viz-summary-row">
            <span>关键冲突</span>
            <span :class="flagClass(!disagreement.critical_conflict)">
              {{ booleanText(disagreement.critical_conflict) }}
            </span>
          </div>
          <div class="viz-summary-row">
            <span>需要人工复核</span>
            <span :class="flagClass(!disagreement.need_human_review)">
              {{ booleanText(disagreement.need_human_review) }}
            </span>
          </div>
        </div>
      </div>

      <div v-if="disagreement.reasons?.length" class="viz-reasons">
        <div class="viz-section-title">分歧原因</div>
        <ul>
          <li v-for="reason in disagreement.reasons" :key="reason">{{ reason }}</li>
        </ul>
      </div>

      <div v-if="disagreement.pairs?.length" class="viz-pairs">
        <div class="viz-section-title">逐类对比</div>
        <div class="pair-grid">
          <div
            v-for="(pair, index) in disagreement.pairs"
            :key="`${pair.category}-${index}`"
            class="pair-card"
          >
            <div class="pair-head">
              <span class="pair-category">{{ pair.category }}</span>
              <el-tag :type="pair.factual_conflict ? 'danger' : 'success'" size="small">
                {{ pair.factual_conflict ? '事实冲突' : '无事实冲突' }}
              </el-tag>
            </div>
            <div class="pair-row">
              <span>类别一致性</span>
              <el-progress
                :percentage="Math.round(pair.category_score * 100)"
                :stroke-width="8"
              />
            </div>
            <div class="pair-row">
              <span>严重度 A / B</span>
              <span>
                {{ pair.severity_a ?? '无' }} / {{ pair.severity_b ?? '无' }}
                <template v-if="pair.severity_difference !== null">
                  （差 {{ pair.severity_difference }}）
                </template>
              </span>
            </div>
            <div class="pair-row">
              <span>置信度 A / B</span>
              <span>
                {{ confidenceText(pair.confidence_a) }} /
                {{ confidenceText(pair.confidence_b) }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <p v-else-if="disagreement.mode !== 'pair'" class="viz-no-pair">
        {{ modeLabel }}模式下未进行双模型逐类对比
      </p>
    </template>
    <el-empty v-else description="暂未保存分歧检测数据" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import type { Assessment } from '../types'

const props = defineProps<{
  assessment: Assessment
}>()

const disagreement = computed(() => props.assessment.disagreement ?? null)

const agreementPercent = computed(() =>
  disagreement.value?.agreement_available
    ? Math.round((disagreement.value.agreement_score ?? 0) * 100)
    : 0,
)

const agreementColor = computed(() => {
  if (agreementPercent.value >= 80) return '#16a34a'
  if (agreementPercent.value >= 60) return '#d97706'
  return '#dc2626'
})

const modeLabel = computed(() => {
  const map: Record<string, string> = {
    pair: '双模型交叉',
    single: '单模型',
    partial: '部分成功',
    fallback: '降级 Mock',
    mock: 'Mock 模式',
  }
  const mode = disagreement.value?.mode || ''
  return map[mode] || mode || '未知'
})

const modeTag = computed<'success' | 'warning' | 'danger' | 'info'>(() => {
  const mode = disagreement.value?.mode || ''
  if (mode === 'pair') return 'success'
  if (mode === 'partial') return 'warning'
  if (mode === 'fallback') return 'danger'
  return 'info'
})

function booleanText(value: boolean) {
  return value ? '是' : '否'
}

function flagClass(positive: boolean) {
  return positive ? 'flag-ok' : 'flag-bad'
}

function confidenceText(value: number) {
  return `${Math.round(value * 100)}%`
}
</script>

<style scoped>
.disagreement-viz {
  min-height: 120px;
}

.viz-overview {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.viz-score {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.viz-score-label,
.viz-section-title {
  color: #334155;
  font-size: 13px;
  font-weight: 600;
}

.viz-score-hint {
  margin: 0;
  color: #94a3b8;
  font-size: 12px;
}

.viz-summary {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 220px;
}

.viz-summary-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  color: #475569;
  font-size: 13px;
}

.flag-ok {
  color: #16a34a;
}

.flag-bad {
  color: #dc2626;
}

.viz-reasons {
  margin-bottom: 14px;
}

.viz-reasons ul {
  margin: 8px 0 0;
  padding-left: 18px;
  color: #b45309;
  font-size: 13px;
}

.viz-reasons li {
  margin-bottom: 4px;
}

.pair-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
  margin-top: 8px;
}

.pair-card {
  padding: 10px 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}

.pair-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.pair-category {
  color: #1e3a8a;
  font-size: 13px;
  font-weight: 600;
}

.pair-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
  color: #475569;
  font-size: 12px;
}

.pair-row .el-progress {
  flex: 1;
  max-width: 160px;
}

.viz-no-pair {
  margin: 0;
  color: #64748b;
  font-size: 13px;
}
</style>
