<template>
  <div class="legal-evidence">
    <div class="legal-overview">
      <span class="legal-count">法规证据 {{ evidenceList.length }} 条</span>
      <span class="legal-count">已采用为证据 {{ usedCount }} 条</span>
      <el-tag
        v-if="judgeInfo"
        :type="judgeInfo.supported ? 'success' : 'warning'"
        effect="light"
      >
        {{ judgeInfo.supported ? '证据支持' : '证据不足' }}
      </el-tag>
    </div>

    <el-empty
      v-if="!evidenceList.length"
      description="暂无检索到法规依据，需人工复核"
    />

    <div v-else class="legal-list">
      <div
        v-for="item in evidenceList"
        :key="item.id || `${item.source}-${item.text || item.snippet || ''}`"
        class="legal-item"
      >
        <div class="legal-item-head">
          <div class="legal-title">
            <span class="legal-source">{{ item.document || item.source }}</span>
            <span v-if="item.article" class="legal-article">{{ item.article }}</span>
          </div>
          <el-tag :type="statusTag(item)" size="small">{{ statusLabel(item) }}</el-tag>
        </div>
        <p v-if="item.source !== item.document" class="legal-source-line">
          来源：{{ item.source }}
        </p>
        <div class="legal-meta">
          <span v-if="item.version">版本 {{ item.version }}</span>
          <span v-if="item.effective_date">生效 {{ item.effective_date }}</span>
          <span v-if="item.score !== undefined">
            相关度 {{ Math.round(item.score * 100) }}%
          </span>
          <span v-if="item.risk_type">类型 {{ item.risk_type }}</span>
          <span v-if="item.scene">场景 {{ item.scene }}</span>
        </div>
        <p class="legal-text">{{ item.text || item.snippet }}</p>
        <div v-if="item.tags?.length" class="legal-tags">
          <el-tag v-for="tag in item.tags" :key="tag" size="small" type="info">
            {{ tag }}
          </el-tag>
        </div>
        <p v-if="item.is_demo" class="legal-demo">
          演示数据，不作为法规证据
        </p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import type { Assessment, EvidenceItem } from '../types'

const props = defineProps<{
  assessment: Assessment
}>()

const evidenceList = computed(() => props.assessment.evidence ?? [])
const judgeInfo = computed(() => props.assessment.evidence_judge ?? null)

const usedIds = computed(() => {
  const set = new Set<string>()
  for (const finding of props.assessment.findings ?? []) {
    for (const id of finding.evidence_ids ?? []) set.add(id)
  }
  return set
})

const usedCount = computed(
  () =>
    evidenceList.value.filter(
      (item) => Boolean(item.id) && usedIds.value.has(item.id || ''),
    ).length,
)

function statusLabel(item: EvidenceItem) {
  if (item.is_demo) return '演示数据'
  if (item.id && usedIds.value.has(item.id)) return '已采用为证据'
  return '检索未采用'
}

function statusTag(item: EvidenceItem): 'success' | 'warning' | 'info' {
  if (item.is_demo) return 'info'
  if (item.id && usedIds.value.has(item.id)) return 'success'
  return 'warning'
}
</script>

<style scoped>
.legal-evidence {
  min-height: 80px;
}

.legal-overview {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.legal-count {
  color: #475569;
  font-size: 13px;
}

.legal-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.legal-item {
  padding: 10px 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}

.legal-item-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

.legal-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.legal-source {
  font-weight: 600;
  color: #155e75;
  font-size: 13px;
}

.legal-article {
  color: #1e40af;
  font-size: 12px;
}

.legal-source-line {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 12px;
}

.legal-meta {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 8px;
  color: #64748b;
  font-size: 12px;
}

.legal-text {
  margin: 8px 0 0;
  color: #475569;
  font-size: 13px;
}

.legal-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 8px;
}

.legal-demo {
  margin: 8px 0 0;
  color: #b45309;
  font-size: 12px;
}
</style>
