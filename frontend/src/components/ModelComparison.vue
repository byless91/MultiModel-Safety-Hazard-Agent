<template>
  <div class="model-comparison">
    <div class="comparison-overview">
      <el-tag :type="modeTag" effect="light">{{ modeLabel }}</el-tag>
    </div>

    <el-empty v-if="!modelResults.length" description="暂无双模型结果数据" />

    <div v-else class="model-grid">
      <div v-for="run in modelResults" :key="run.provider" class="model-card">
        <div class="model-card-head">
          <span class="model-name">{{ providerLabel(run.provider) }}</span>
          <el-tag :type="statusTag(run.status)" size="small">
            {{ statusLabel(run.status) }}
          </el-tag>
        </div>
        <div class="model-meta">
          <span>模型 {{ run.model }}</span>
          <span v-if="run.latency_ms">耗时 {{ run.latency_ms }}ms</span>
          <span v-if="run.retry_count">重试 {{ run.retry_count }}</span>
        </div>
        <p v-if="run.error_message" class="model-error">{{ run.error_message }}</p>
        <p v-if="run.status === 'failed'" class="model-failed">
          模型调用失败，结果缺失，需人工复核
        </p>
        <div v-else-if="run.analysis" class="model-analysis">
          <div class="model-analysis-row">
            视觉置信度 {{ confidenceText(run.analysis.vision_confidence ?? 0) }}
          </div>
          <p v-if="run.analysis.hazard_hints?.length" class="model-hints">
            {{ run.analysis.hazard_hints.join('、') }}
          </p>
          <div v-if="run.analysis.hazards?.length" class="model-findings">
            <div
              v-for="finding in run.analysis.hazards"
              :key="finding.hazard_type"
              class="model-finding"
            >
              <div class="model-finding-head">
                <span>{{ finding.hazard_type }}</span>
                <span v-if="finding.severity">严重度 {{ finding.severity }}/3</span>
                <span v-if="finding.confidence !== undefined">
                  置信度 {{ confidenceText(finding.confidence) }}
                </span>
              </div>
              <p v-if="finding.description">{{ finding.description }}</p>
              <ul v-if="finding.observed_facts?.length" class="fact-list">
                <li v-for="fact in finding.observed_facts" :key="fact">{{ fact }}</li>
              </ul>
            </div>
          </div>
          <p v-else class="model-no-findings">未输出结构化隐患</p>
        </div>
        <p v-else-if="run.status === 'mock_fallback'" class="model-fallback">
          已降级 Mock，结果仅作工作流验证，不视为真实模型能力
        </p>
      </div>
    </div>

  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import type { Assessment } from '../types'

const props = defineProps<{
  assessment: Assessment
}>()

const multiModel = computed(() => props.assessment.multi_model ?? null)
const modelResults = computed(() => multiModel.value?.results ?? [])

const modeLabel = computed(() => {
  const mode = multiModel.value?.ensemble_mode || ''
  const map: Record<string, string> = {
    full: '双模型完整并行',
    partial: '部分模型成功',
    fallback: '全部失败，已降级 Mock',
    single_real: '单真实模型',
    mock: 'Mock 模式',
  }
  return map[mode] || '结果未知'
})

const modeTag = computed<'success' | 'warning' | 'danger' | 'info'>(() => {
  const mode = multiModel.value?.ensemble_mode || ''
  if (mode === 'full') return 'success'
  if (mode === 'partial') return 'warning'
  if (mode === 'fallback') return 'danger'
  return 'info'
})

function providerLabel(provider: string) {
  if (provider === 'dashscope') return 'Qwen-VL'
  if (provider === 'zhipu') return 'GLM-V'
  return 'Mock'
}

function statusLabel(status: string) {
  if (status === 'success') return '成功'
  if (status === 'failed') return '失败'
  if (status === 'mock_fallback') return 'Mock 降级'
  return '未知'
}

function statusTag(status: string): 'success' | 'danger' | 'warning' | 'info' {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'mock_fallback') return 'warning'
  return 'info'
}

function confidenceText(value: number) {
  return `${Math.round(value * 100)}%`
}

</script>

<style scoped>
.model-comparison {
  min-height: 80px;
}

.comparison-overview {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.model-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 14px;
  margin-bottom: 14px;
}

.model-card {
  padding: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}

.model-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.model-name {
  font-size: 15px;
  font-weight: 700;
  color: #1e3a8a;
}

.model-meta {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
  color: #64748b;
  font-size: 12px;
}

.model-error,
.model-failed {
  margin: 0 0 8px;
  color: #b91c1c;
  font-size: 12px;
}

.model-fallback {
  margin: 0;
  color: #b45309;
  font-size: 12px;
}

.model-analysis-row {
  margin-bottom: 6px;
  color: #334155;
  font-size: 12px;
}

.model-hints {
  margin: 0 0 8px;
  color: #475569;
  font-size: 12px;
}

.model-findings {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.model-finding {
  padding: 8px 10px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}

.model-finding-head {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  color: #334155;
  font-size: 12px;
  font-weight: 600;
}

.model-finding p {
  margin: 6px 0 0;
  color: #475569;
  font-size: 12px;
}

.fact-list {
  margin: 6px 0 0;
  padding-left: 16px;
  color: #64748b;
  font-size: 12px;
}

.model-no-findings {
  margin: 0;
  color: #94a3b8;
  font-size: 12px;
}

</style>
