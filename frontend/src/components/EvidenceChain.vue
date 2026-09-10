<template>
  <div class="evidence-chain">
    <div class="chain-overview">
      <el-tag :type="overallType" effect="light">{{ overallLabel }}</el-tag>
      <span class="overview-counts">
        视觉证据 {{ evidenceCounts.visual }} 条 · 法规证据 {{ evidenceCounts.legal }} 条
      </span>
      <span v-if="ruleVersion" class="overview-version">规则版本 {{ ruleVersion }}</span>
    </div>

    <el-empty
      v-if="!assessment.findings?.length"
      description="暂无证据链可展示"
    />

    <div v-else class="finding-chains">
      <div
        v-for="(entry, index) in findingsWithLinks"
        :key="entry.finding.finding_id"
        class="chain-card"
      >
        <div class="chain-card-head">
          <span class="chain-index">#{{ index + 1 }}</span>
          <span class="chain-category">{{ entry.finding.category }}</span>
          <el-tag :type="statusTag(entry.finding.evidence_status)" size="small">
            {{ statusLabel(entry.finding.evidence_status) }}
          </el-tag>
        </div>
        <p v-if="entry.finding.description" class="chain-description">
          {{ entry.finding.description }}
        </p>

        <div class="chain-step">
          <div class="chain-step-title">① 视觉事实</div>
          <ul v-if="entry.finding.observed_facts?.length" class="chain-list">
            <li v-for="fact in entry.finding.observed_facts" :key="fact">{{ fact }}</li>
          </ul>
          <p v-else class="chain-none">暂无可靠视觉事实，需人工复核</p>
          <div v-if="entry.finding.locations?.length" class="chain-locations">
            <span
              v-for="loc in entry.finding.locations"
              :key="`${loc.image_id || ''}-${loc.location_text || ''}`"
              class="location-chip"
            >
              {{ locationLabel(loc) }}
            </span>
          </div>
        </div>

        <div class="chain-step">
          <div class="chain-step-title">② 模型交叉验证</div>
          <p class="chain-model">
            {{ entry.finding.model_support?.join(' + ') || entry.finding.source || '单模型' }}
          </p>
        </div>

        <div class="chain-step">
          <div class="chain-step-title">③ 风险计算</div>
          <p class="chain-risk">
            <template
              v-if="entry.finding.risk_score !== undefined && entry.finding.risk_score !== null"
            >
              风险分 {{ entry.finding.risk_score }} / 100 · {{ riskLevelLabel(entry.finding.risk_level) }}
            </template>
            <template
              v-else-if="assessment.risk_score !== undefined && assessment.risk_score !== null"
            >
              风险分 {{ assessment.risk_score }} / 100 · {{ riskLevelLabel(assessment.risk_label) }}
            </template>
            <span v-else>暂无可靠风险评分，需人工复核</span>
            <span v-if="ruleVersion" class="chain-version">规则 {{ ruleVersion }}</span>
          </p>
        </div>

        <div class="chain-step">
          <div class="chain-step-title">④ 法规依据</div>
          <div v-if="entry.linkedEvidence.length" class="chain-evidence-list">
            <div
              v-for="item in entry.linkedEvidence"
              :key="item.id || `${item.source}-${item.text || item.snippet}`"
              class="chain-evidence-item"
            >
              <div class="chain-evidence-head">
                <span class="chain-evidence-source">{{ item.source }}</span>
                <span v-if="item.article" class="chain-evidence-article">{{ item.article }}</span>
                <span v-if="item.score !== undefined" class="chain-evidence-score">
                  {{ Math.round(item.score * 100) }}%
                </span>
              </div>
              <p class="chain-evidence-text">{{ item.text || item.snippet }}</p>
            </div>
          </div>
          <p v-else class="chain-none">未检索到可追溯的法规证据，需人工复核</p>
        </div>

        <div class="chain-step">
          <div class="chain-step-title">⑤ 证据判定</div>
          <p class="chain-verdict">{{ evidenceVerdictText(entry.finding) }}</p>
          <ul v-if="entry.finding.unsupported_claims?.length" class="chain-unsupported">
            <li v-for="claim in entry.finding.unsupported_claims" :key="claim">{{ claim }}</li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import type {
  Assessment,
  EvidenceItem,
  Finding,
  FindingLocation,
} from '../types'

const props = defineProps<{
  assessment: Assessment
}>()

const evidenceById = computed(() => {
  const map = new Map<string, EvidenceItem>()
  for (const item of props.assessment.evidence) {
    if (item.id) map.set(item.id, item)
  }
  return map
})

const imageById = computed(() => {
  const map = new Map(
    props.assessment.images.map((image) => [image.id, image]),
  )
  return map
})

interface ChainEntry {
  finding: Finding
  linkedEvidence: EvidenceItem[]
}

const findingsWithLinks = computed<ChainEntry[]>(() =>
  (props.assessment.findings ?? []).map((finding) => ({
    finding,
    linkedEvidence: (finding.evidence_ids ?? [])
      .map((id) => evidenceById.value.get(id))
      .filter((item): item is EvidenceItem => Boolean(item)),
  })),
)

const overallLabel = computed(() => {
  const judge = props.assessment.evidence_judge
  if (!judge) return '证据未判定'
  return judge.supported ? '证据支持' : '证据不足'
})

const overallType = computed<'success' | 'warning' | 'info'>(() => {
  const judge = props.assessment.evidence_judge
  if (judge?.supported) return 'success'
  if (judge) return 'warning'
  return 'info'
})

const evidenceCounts = computed(() => {
  const judge = props.assessment.evidence_judge
  const locations = (props.assessment.findings ?? []).reduce(
    (total, finding) => total + (finding.locations?.length ?? 0),
    0,
  )
  return {
    visual: judge?.visual_evidence_count ?? locations,
    legal: judge?.retrieval_evidence_count ?? props.assessment.evidence.length,
  }
})

const ruleVersion = computed(
  () =>
    props.assessment.risk_result?.rule_version ||
    props.assessment.risk_rule_version,
)

function statusLabel(status: string) {
  if (status === 'supported') return '证据支持'
  if (status === 'insufficient') return '证据不足'
  return '待判定'
}

function statusTag(status: string): 'success' | 'warning' | 'info' {
  if (status === 'supported') return 'success'
  if (status === 'insufficient') return 'warning'
  return 'info'
}

function locationLabel(location: FindingLocation) {
  const matchedImage = location.image_id
    ? imageById.value.get(location.image_id)
    : undefined
  const parts: string[] = []
  if (matchedImage) {
    parts.push(`图片 ${matchedImage.filename}`)
  } else if (location.image_id) {
    parts.push(`图片ID ${location.image_id} 未对应上传图片`)
  }
  if (location.location_text) parts.push(location.location_text)
  if (location.bbox?.length) parts.push(`bbox [${location.bbox.join(', ')}]`)
  return parts.length ? parts.join('：') : '暂无位置证据'
}

function riskLevelLabel(level: string | null | undefined) {
  const map: Record<string, string> = {
    low: '低风险',
    medium: '中风险',
    high: '高风险',
  }
  return (level && map[level]) || level || '未评级'
}

function evidenceVerdictText(finding: Finding) {
  if (finding.evidence_status === 'supported') {
    const score = finding.support_score ?? 0
    return `证据支持，支持度 ${Math.round(score * 100)}%`
  }
  if (finding.evidence_status === 'insufficient') {
    return '证据不足，需要人工复核'
  }
  return '证据判定待确认'
}
</script>

<style scoped>
.evidence-chain {
  min-height: 80px;
}

.chain-overview {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.overview-counts {
  color: #475569;
  font-size: 13px;
}

.overview-version {
  color: #94a3b8;
  font-size: 12px;
}

.finding-chains {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.chain-card {
  padding: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}

.chain-card-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.chain-index {
  color: #94a3b8;
  font-size: 12px;
}

.chain-category {
  font-weight: 600;
  color: #1e3a8a;
}

.chain-description {
  margin: 0 0 12px;
  color: #475569;
  font-size: 13px;
}

.chain-step {
  margin-bottom: 12px;
}

.chain-step:last-child {
  margin-bottom: 0;
}

.chain-step-title {
  margin-bottom: 6px;
  color: #334155;
  font-size: 12px;
  font-weight: 600;
}

.chain-list {
  margin: 0;
  padding-left: 18px;
  color: #475569;
  font-size: 13px;
}

.chain-list li {
  margin-bottom: 4px;
}

.chain-none {
  margin: 0;
  color: #b45309;
  font-size: 13px;
}

.chain-locations {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.location-chip {
  padding: 3px 8px;
  border: 1px solid #dbeafe;
  border-radius: 4px;
  background: #eff6ff;
  color: #1e40af;
  font-size: 12px;
}

.chain-model,
.chain-risk,
.chain-verdict {
  margin: 0;
  color: #334155;
  font-size: 13px;
}

.chain-version {
  margin-left: 8px;
  color: #94a3b8;
  font-size: 12px;
}

.chain-evidence-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.chain-evidence-item {
  padding: 8px 10px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}

.chain-evidence-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

.chain-evidence-source {
  font-weight: 600;
  color: #155e75;
  font-size: 12px;
}

.chain-evidence-article,
.chain-evidence-score {
  color: #64748b;
  font-size: 12px;
  white-space: nowrap;
}

.chain-evidence-text {
  margin: 6px 0 0;
  color: #475569;
  font-size: 12px;
}

.chain-unsupported {
  margin: 8px 0 0;
  padding-left: 18px;
  color: #b45309;
  font-size: 12px;
}
</style>
