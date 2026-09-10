<template>
  <div v-loading="loading" class="result-wrap">
    <el-alert
      v-if="assessment.status === 'needs_more_info'"
      title="需要补充现场信息"
      type="warning"
      :closable="false"
      show-icon
    >
      <div class="followup-box">
        <ul class="question-list">
          <li v-for="question in assessment.followup_questions" :key="question">{{ question }}</li>
        </ul>
        <el-input
          v-model="answer"
          type="textarea"
          :rows="3"
          placeholder="补充隐患位置、危险程度、现场环境等信息"
        />
        <el-button
          class="followup-button"
          type="primary"
          :disabled="!answer.trim()"
          @click="emit('followup', answer.trim())"
        >
          <el-icon><Promotion /></el-icon>
          提交补充信息
        </el-button>
      </div>
    </el-alert>

    <template v-else-if="report">
      <div class="result-header">
        <div>
          <h3 class="result-title">
            {{ assessment.hazard_category || '隐患类型待确认' }}
            <el-tag :type="levelTag" effect="dark">{{ levelLabel }}</el-tag>
          </h3>
          <p class="result-summary">{{ report.summary }}</p>
        </div>
        <div class="confidence-wrap">
          <span class="confidence-label">综合置信度</span>
          <el-progress
            type="circle"
            :percentage="Math.round((assessment.confidence || 0) * 100)"
            :width="72"
            :stroke-width="8"
            :color="levelColor"
          />
        </div>
      </div>

      <div class="plain-summary" :class="`plain-${assessment.status}`">
        <div class="plain-summary-title">
          <el-icon><InfoFilled /></el-icon>
          结果怎么理解
        </div>
        <div class="plain-summary-grid">
          <div class="plain-item">
            <span class="plain-label">风险等级</span>
            <span class="plain-value">{{ riskDesc }}</span>
          </div>
          <div class="plain-item">
            <span class="plain-label">AI 把握程度</span>
            <span class="plain-value">{{ confidenceText }}</span>
          </div>
          <div class="plain-item">
            <span class="plain-label">法规依据</span>
            <span class="plain-value">{{ evidenceText }}</span>
          </div>
          <div class="plain-item">
            <span class="plain-label">下一步</span>
            <span class="plain-value next-step">{{ nextStepText }}</span>
          </div>
        </div>
      </div>

      <el-alert
        v-if="assessment.status === 'needs_review'"
        title="该结果需要人工复核"
        type="warning"
        :closable="false"
        show-icon
      />

      <el-card
        v-if="
          (assessment.risk_score !== undefined && assessment.risk_score !== null) ||
          assessment.risk_result
        "
        class="risk-card"
      >
        <template #header>风险引擎判定与解释</template>
        <RiskExplanation :assessment="assessment" />
      </el-card>

      <el-card class="model-comparison-card">
        <template #header>模型 A/B 对比</template>
        <ModelComparison :assessment="assessment" />
      </el-card>

      <el-card v-if="assessment.disagreement" class="disagreement-viz-card">
        <template #header>分歧可视化</template>
        <DisagreementViz :assessment="assessment" />
      </el-card>

      <div class="result-grid">
        <el-card class="result-card">
          <template #header>处置建议</template>
          <h4>现场处置</h4>
          <ul class="action-list">
            <li v-for="action in report.immediate_actions" :key="action">{{ action }}</li>
          </ul>
          <h4>长效机制</h4>
          <ul class="action-list">
            <li v-for="action in report.long_term_actions" :key="action">{{ action }}</li>
          </ul>
        </el-card>

        <el-card class="result-card">
          <template #header>整改工单</template>
          <el-descriptions :column="1" size="small" border>
            <el-descriptions-item label="类别">{{ report.work_order.category }}</el-descriptions-item>
            <el-descriptions-item label="等级">{{ report.work_order.level }}</el-descriptions-item>
            <el-descriptions-item label="时限">{{ report.work_order.deadline }}</el-descriptions-item>
            <el-descriptions-item label="位置">{{ report.work_order.location }}</el-descriptions-item>
            <el-descriptions-item label="验收">
              {{ report.work_order.acceptance }}
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </div>

      <el-card class="evidence-card">
        <template #header>
          <span>法规证据（{{ assessment.evidence.length }}）</span>
        </template>
        <LegalEvidence :assessment="assessment" />
      </el-card>

      <el-card
        v-if="assessment.evidence_judge || assessment.findings?.length"
        class="evidence-judge-card"
      >
        <template #header>
          <div class="evidence-judge-head">
            <span>证据链判定</span>
            <el-tag
              v-if="assessment.evidence_judge"
              :type="assessment.evidence_judge.supported ? 'success' : 'warning'"
              effect="light"
            >
              {{ assessment.evidence_judge.supported ? '证据支持' : '证据不足' }}
            </el-tag>
          </div>
        </template>
        <div v-for="finding in evidenceFindings" :key="finding.finding_id" class="judge-finding">
          <div class="judge-finding-head">
            <span class="finding-category">{{ finding.category }}</span>
            <el-tag :type="finding.supported ? 'success' : 'warning'" size="small">
              {{ finding.supported ? '支持' : '不足' }}
            </el-tag>
            <span v-if="finding.support_score !== undefined" class="support-score">
              支持度 {{ Math.round((finding.support_score || 0) * 100) }}%
            </span>
          </div>
          <div v-if="finding.evidence_ids?.length" class="evidence-ids">
            依据：{{ finding.evidence_ids.join('、') }}
          </div>
          <ul v-if="finding.unsupported_claims?.length" class="unsupported-list">
            <li v-for="claim in finding.unsupported_claims" :key="claim">{{ claim }}</li>
          </ul>
          <div v-if="findingLocations(finding).length" class="location-row">
            <span
              v-for="(loc, index) in findingLocations(finding)"
              :key="loc.image_id || loc.location_text || `loc-${index}`"
              class="location-chip"
            >
              <template v-if="loc.image_id">图片 {{ loc.image_id }}</template>
              <template v-if="loc.location_text">：{{ loc.location_text }}</template>
              <span v-if="loc.bbox"> bbox [{{ loc.bbox.join(', ') }}]</span>
            </span>
          </div>
        </div>
        <p v-if="assessment.evidence_judge" class="judge-counts">
          视觉证据 {{ assessment.evidence_judge.visual_evidence_count }} 条，
          法规证据 {{ assessment.evidence_judge.retrieval_evidence_count }} 条
        </p>
      </el-card>

      <el-card class="hazard-overlay-card">
        <template #header>隐患定位（可选 Bounding Box）</template>
        <HazardOverlay :assessment="assessment" />
      </el-card>

      <el-card class="evidence-chain-card">
        <template #header>证据链</template>
        <EvidenceChain :assessment="assessment" />
      </el-card>

      <el-card class="rect-card">
        <template #header>
          <div class="rect-head">
            <span>整改回传</span>
            <el-tag v-if="assessment.rectification_status" :type="rectTag" effect="light">
              {{ rectLabel }}
            </el-tag>
          </div>
        </template>
        <el-steps
          v-if="assessment.rectification_status"
          :active="rectActiveIndex"
          finish-status="success"
          class="rect-steps"
          simple
        >
          <el-step
            v-for="step in rectSteps"
            :key="step.value"
            :title="step.label"
          />
        </el-steps>
        <div v-if="comparePairs.length" class="compare-grid">
          <div
            v-for="(pair, index) in comparePairs"
            :key="`${pair.original.id}-${pair.rectification.id}`"
            class="compare-pair"
          >
            <div class="compare-pair-head">
              <span>第 {{ index + 1 }} 组对比</span>
              <span v-if="comparisonMeta" class="compare-pair-status">
                AI 比对覆盖 {{ comparisonMeta.pair_count }} 组
              </span>
            </div>
            <div class="compare-columns">
              <div class="compare-column">
                <div class="compare-label">整改前</div>
                <el-image
                  v-if="pair.original.url"
                  :src="pair.original.url"
                  :preview-src-list="[pair.original.url]"
                  fit="cover"
                  class="thumb"
                />
                <span v-else class="compare-missing">暂无证据</span>
              </div>
              <div class="compare-column">
                <div class="compare-label">整改后</div>
                <el-image
                  v-if="pair.rectification.url"
                  :src="pair.rectification.url"
                  :preview-src-list="[pair.rectification.url]"
                  fit="cover"
                  class="thumb"
                />
                <span v-else class="compare-missing">暂无证据</span>
              </div>
            </div>
          </div>
        </div>
        <div v-if="!rectImages.length && originals.length" class="original-only">
          <div class="compare-label">整改前（暂无整改后照片）</div>
          <div class="thumb-row">
            <template v-for="img in originals" :key="img.id">
              <el-image
                v-if="img.url"
                :src="img.url"
                :preview-src-list="[img.url]"
                fit="cover"
                class="thumb"
              />
            </template>
          </div>
        </div>
        <p v-if="unmatchedNote" class="compare-unmatched">{{ unmatchedNote }}</p>
        <div v-if="!rectImages.length" class="compare-empty">
          <el-alert type="warning" :closable="false" title="暂无整改后照片，无法进行前后对比" />
        </div>
        <p v-if="assessment.rectification_note" class="rect-note">
          {{ assessment.rectification_note }}
        </p>
        <div
          v-if="
            assessment.rectification_score !== undefined &&
            assessment.rectification_score !== null
          "
          class="compare-result"
        >
          <div class="compare-result-head">
            <span>整改完成度</span>
            <span class="compare-score">
              {{ Math.round(assessment.rectification_score * 100) }}%
            </span>
          </div>
          <el-progress
            :percentage="Math.round(assessment.rectification_score * 100)"
            :stroke-width="10"
            :color="rectColor"
          />
          <p v-if="assessment.rectification_analysis?.summary" class="compare-summary">
            {{ assessment.rectification_analysis.summary }}
          </p>
          <ul
            v-if="assessment.rectification_analysis?.issues?.length"
            class="issue-list"
          >
            <li
              v-for="issue in assessment.rectification_analysis.issues"
              :key="issue"
            >
              {{ issue }}
            </li>
          </ul>
          <div v-if="completionAssessment" class="completion-box">
            <div class="completion-head">
              <el-tag :type="verdictTag" effect="light">{{ verdictLabel }}</el-tag>
              <span v-if="completionAssessment.completion_confidence" class="completion-conf">
                置信度 {{ Math.round(completionAssessment.completion_confidence * 100) }}%
              </span>
            </div>
            <ul v-if="completionAssessment.reasons.length" class="completion-reasons">
              <li v-for="reason in completionAssessment.reasons" :key="reason">
                {{ reason }}
              </li>
            </ul>
            <p v-if="completionAssessment.rule_version" class="completion-version">
              规则版本：{{ completionAssessment.rule_version }}
            </p>
          </div>
        </div>
        <div v-if="rectHistory.length" class="rect-history">
          <h4>整改流程记录</h4>
          <ul>
            <li v-for="(entry, index) in rectHistory" :key="`${entry.created_at}-${index}`">
              {{ entry.action }}（{{ statusLabel(entry.from_status) }} → {{ statusLabel(entry.to_status) }}）
              <span class="rect-history-meta">
                {{ formatTime(entry.created_at) }}<template v-if="entry.by"> · {{ entry.by }}</template>
              </span>
              <span v-if="entry.note" class="rect-history-note">{{ entry.note }}</span>
            </li>
          </ul>
        </div>
        <div v-if="canSubmitPhotos" class="rect-form">
          <el-upload
            v-model:file-list="rectFiles"
            :auto-upload="false"
            :limit="3"
            accept="image/*"
            multiple
            list-type="picture-card"
          >
            <el-icon><Plus /></el-icon>
          </el-upload>
          <el-input v-model="rectNote" type="textarea" :rows="2" placeholder="整改说明（可选）" />
        </div>
        <div class="rect-actions">
            <el-button v-if="canStart" type="primary" :loading="store.loading" @click="onStartRectification">
              <el-icon><EditPen /></el-icon>
              开始整改
            </el-button>
            <el-button
              v-if="canSubmitPhotos"
              type="primary"
              :loading="store.loading"
              :disabled="rectFiles.length === 0"
              @click="onSubmitRectification"
            >
              提交整改照片
            </el-button>
            <el-button v-if="rectImages.length" @click="onRecompare">
              <el-icon><RefreshRight /></el-icon>
              重新 AI 比对
            </el-button>
            <el-button
              v-if="canVerify"
              type="success"
              @click="onRectificationTransition('verified', '已确认整改完成')"
            >
              确认整改完成
            </el-button>
            <el-button
              v-if="canVerify || canClose"
              type="warning"
              @click="onRectificationTransition('rectifying', '已退回整改')"
            >
              退回整改
            </el-button>
            <el-button
              v-if="canClose"
              type="primary"
              @click="onRectificationTransition('closed', '工单已关闭')"
            >
              关闭工单
            </el-button>
            <el-button
              v-if="canReopen"
              type="primary"
              @click="onRectificationTransition('open', '工单已重新打开')"
            >
              重新打开
            </el-button>
        </div>
      </el-card>

      <el-card v-if="humanReviewVisible" class="human-review-card">
        <template #header>
          <div class="human-review-head">
            <span>人工复核</span>
            <el-tag
              :type="assessment.confirmed ? 'success' : assessment.status === 'needs_review' ? 'warning' : 'primary'"
              effect="light"
            >
              {{ humanReviewTagLabel }}
            </el-tag>
          </div>
        </template>
        <ul v-if="assessment.review_reasons?.length" class="human-review-reasons">
          <li v-for="reason in assessment.review_reasons" :key="reason">
            {{ reason }}
          </li>
        </ul>
        <div v-if="humanResolution" class="human-resolution">
          <p>复核结论：{{ humanResolution.confirmed ? '确认通过' : '需重新研判' }}</p>
          <p v-if="humanResolution.reviewer">复核人：{{ humanResolution.reviewer }}</p>
          <p v-if="humanResolution.note">复核意见：{{ humanResolution.note }}</p>
          <p v-if="humanResolution.resolved_at">
            复核时间：{{ formatTime(humanResolution.resolved_at) }}
          </p>
        </div>
        <el-button
          v-if="!assessment.confirmed"
          type="primary"
          :loading="store.loading"
          @click="emit('confirm')"
        >
          <el-icon><CircleCheck /></el-icon>
          确认结果并定稿
        </el-button>
      </el-card>

      <div class="footer-actions">
        <el-button @click="onDownload">
          <el-icon><Download /></el-icon>
          下载报告
        </el-button>
        <span class="disclaimer">{{ report.disclaimer }}</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ElMessage, type UploadFile } from 'element-plus'
import { computed, ref } from 'vue'

import { useAssessmentStore } from '../stores/assessment'
import type { Assessment, AssessmentImage, FindingLocation } from '../types'
import EvidenceChain from './EvidenceChain.vue'
import DisagreementViz from './DisagreementViz.vue'
import HazardOverlay from './HazardOverlay.vue'
import LegalEvidence from './LegalEvidence.vue'
import ModelComparison from './ModelComparison.vue'
import RiskExplanation from './RiskExplanation.vue'

const props = defineProps<{
  assessment: Assessment
  loading?: boolean
}>()

const emit = defineEmits<{
  followup: [answer: string]
  confirm: []
  updated: [assessment: Assessment]
}>()

const answer = ref('')
const rectFiles = ref<UploadFile[]>([])
const rectNote = ref('')
const report = computed(() => props.assessment.report)
const store = useAssessmentStore()

function byImageTime(a: AssessmentImage, b: AssessmentImage) {
  const timeA = a.created_at || ''
  const timeB = b.created_at || ''
  const time = timeA.localeCompare(timeB)
  return time !== 0 ? time : a.id.localeCompare(b.id)
}

const originals = computed(() =>
  props.assessment.images
    .filter((image) => image.image_kind === 'original')
    .sort(byImageTime),
)
const rectImages = computed(() =>
  props.assessment.images
    .filter((image) => image.image_kind === 'rectification')
    .sort(byImageTime),
)

const comparisonMeta = computed(
  () => props.assessment.rectification_analysis?.comparison ?? null,
)

const completionAssessment = computed(
  () => props.assessment.rectification_analysis?.assessment ?? null,
)

const verdictLabels: Record<string, string> = {
  resolved_recommended: 'AI 建议判定已完成',
  not_resolved: 'AI 判定未完成',
  insufficient_evidence: '证据不足，无法评估',
  needs_review: '结论冲突，需人工复核',
}

const verdictLabel = computed(() => {
  const verdict = completionAssessment.value?.verdict || ''
  return verdictLabels[verdict] || '待人工复核'
})

const verdictTag = computed<'success' | 'warning' | 'danger' | 'info'>(() => {
  const verdict = completionAssessment.value?.verdict
  if (verdict === 'resolved_recommended') return 'success'
  if (verdict === 'not_resolved') return 'danger'
  if (verdict === 'needs_review') return 'warning'
  return 'info'
})

const comparePairs = computed(() => {
  const count = Math.min(originals.value.length, rectImages.value.length)
  return Array.from({ length: count }, (_, index) => ({
    original: originals.value[index],
    rectification: rectImages.value[index],
  }))
})

const unmatchedNote = computed(() => {
  const meta = comparisonMeta.value
  const before = meta?.original_count ?? originals.value.length
  const after = meta?.rectification_count ?? rectImages.value.length
  if (before === after) return ''
  return `整改前 ${before} 张 / 整改后 ${after} 张，数量不一致，剩余图片无法一一对应，需人工复核。`
})

const evidenceFindings = computed(() => {
  const judgeFindings = props.assessment.evidence_judge?.findings ?? []
  const finalById = new Map(
    (props.assessment.findings ?? []).map((item) => [item.finding_id, item]),
  )
  return judgeFindings.map((item) => ({
    ...item,
    locations: finalById.get(item.finding_id)?.locations ?? [],
  }))
})

function findingLocations(finding: { locations?: FindingLocation[] }) {
  return finding.locations ?? []
}

const rectSteps = [
  { value: 'open', label: '待分派' },
  { value: 'assigned', label: '已分派' },
  { value: 'rectifying', label: '整改中' },
  { value: 'pending_verification', label: '待验证' },
  { value: 'verified', label: '已验证' },
  { value: 'closed', label: '已关闭' },
]

const rectLabels: Record<string, string> = {
  open: '待分派',
  assigned: '已分派',
  rectifying: '整改中',
  pending_verification: '待验证',
  verified: '已验证',
  closed: '已关闭',
}

const rectTag = computed<'success' | 'warning' | 'info' | 'primary'>(() => {
  const status = props.assessment.rectification_status
  if (status === 'verified') return 'success'
  if (status === 'pending_verification') return 'warning'
  if (status === 'rectifying' || status === 'assigned') return 'primary'
  return 'info'
})

const rectLabel = computed(() => {
  const status = props.assessment.rectification_status || ''
  return rectLabels[status] || '未开始整改'
})

const rectActiveIndex = computed(() => {
  const status = props.assessment.rectification_status
  const index = rectSteps.findIndex((item) => item.value === status)
  return index === -1 ? 0 : index
})

const rectHistory = computed(
  () => props.assessment.rectification_meta?.history ?? [],
)

function statusLabel(status: string) {
  return rectLabels[status] || status
}

function formatTime(value?: string) {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString()
}

const canStart = computed(() => {
  const status = props.assessment.rectification_status
  return status === 'open' || status === 'assigned'
})

const canSubmitPhotos = computed(() => {
  const status = props.assessment.rectification_status
  return status === 'open' || status === 'assigned' || status === 'rectifying'
})

const canVerify = computed(
  () => props.assessment.rectification_status === 'pending_verification',
)

const canClose = computed(
  () => props.assessment.rectification_status === 'verified',
)

const canReopen = computed(
  () => props.assessment.rectification_status === 'closed',
)

const rectColor = computed(() => {
  const score = props.assessment.rectification_score ?? 0
  return score >= 0.8 ? '#16a34a' : score >= 0.5 ? '#d97706' : '#94a3b8'
})

const levelTag = computed<'danger' | 'warning' | 'success'>(() => {
  const level = props.assessment.risk_level || 3
  return level === 1 ? 'danger' : level === 2 ? 'warning' : 'success'
})

const levelLabel = computed(() => {
  const level = props.assessment.risk_level
  return level === 1 ? '一级 · 立即处置' : level === 2 ? '二级 · 限期整改' : '三级 · 建议改进'
})

const levelColor = computed(() => {
  const level = props.assessment.risk_level || 3
  return level === 1 ? '#dc2626' : level === 2 ? '#d97706' : '#16a34a'
})

const riskDesc = computed(() => {
  const level = props.assessment.risk_level || 3
  if (level === 1) return '高风险 · 应立即处置'
  if (level === 2) return '中风险 · 尽快整改'
  return '较低风险 · 建议改进'
})

const confidenceText = computed(() => {
  const value = props.assessment.confidence
  if (value === undefined || value === null) return '暂时无法判断'
  const percent = Math.round(value * 100)
  if (value >= 0.8) return `AI 把握较高（${percent}%）`
  if (value >= 0.6) return `AI 把握一般（${percent}%）`
  return `AI 把握较低（${percent}%），请以现场为准`
})

const evidenceText = computed(() => {
  const judge = props.assessment.evidence_judge
  if (judge && judge.supported) return '找到法规依据，可支撑结论'
  if (judge && judge.unsupported_claims?.length) return '法规依据不足，需现场核实'
  if (props.assessment.evidence.length) return '已列出参考资料，请结合现场判断'
  return '暂无参考资料，需现场核实'
})

const nextStepText = computed(() => {
  const status = props.assessment.status
  if (status === 'confirmed') return '结果已确认，可据此开展整改'
  if (status === 'awaiting_human_review' || status === 'needs_review') {
    return '请工作人员现场复核后再定稿'
  }
  if (status === 'needs_more_info') return '请补充现场信息后继续研判'
  return '建议再次现场核实后使用'
})

const humanReviewVisible = computed(
  () =>
    Boolean(
      props.assessment.awaiting_human_review ||
        props.assessment.status === 'needs_review' ||
        props.assessment.review_reasons?.length ||
        props.assessment.human_review?.resolution,
    ),
)

const humanResolution = computed(
  () => props.assessment.human_review?.resolution ?? null,
)

const humanReviewTagLabel = computed(() => {
  if (props.assessment.confirmed) return '已人工确认'
  if (props.assessment.status === 'needs_review') return '需重新研判'
  return '待人工复核'
})

async function onDownload() {
  const { filename, content } = await store.downloadReport(props.assessment.id)
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

async function onSubmitRectification() {
  const files = rectFiles.value
    .map((item) => item.raw)
    .filter((file) => Boolean(file) && file instanceof File) as File[]
  const updated = await store.submitRectification(
    props.assessment.id,
    files,
    rectNote.value,
  )
  emit('updated', updated)
  rectFiles.value = []
  rectNote.value = ''
  ElMessage.success('整改照片已提交')
}

async function onStartRectification() {
  const updated = await store.transitionRectification(
    props.assessment.id,
    'rectifying',
    '开始整改',
  )
  emit('updated', updated)
  ElMessage.success('已开始整改')
}

async function onRectificationTransition(toStatus: string, message: string) {
  const updated = await store.transitionRectification(
    props.assessment.id,
    toStatus,
  )
  emit('updated', updated)
  ElMessage.success(message)
}

async function onRecompare() {
  const updated = await store.compareRectification(props.assessment.id)
  emit('updated', updated)
  ElMessage.success('已完成 AI 前后对比')
}
</script>

<style scoped>
.result-wrap {
  min-height: 120px;
}

.followup-box {
  margin-top: 8px;
}

.question-list {
  margin: 0 0 12px;
  padding-left: 18px;
}

.followup-button {
  margin-top: 12px;
}

.result-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 16px;
}

.plain-summary {
  margin-bottom: 14px;
  padding: 12px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.plain-summary-title {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  color: #334155;
  font-weight: 600;
}

.plain-summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 8px 16px;
}

.plain-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.plain-label {
  color: #64748b;
  font-size: 12px;
}

.plain-value {
  color: #0f172a;
  font-size: 13px;
}

.plain-value.next-step {
  color: #155e75;
  font-weight: 600;
}

@media (max-width: 640px) {
  .plain-summary-grid {
    grid-template-columns: 1fr;
  }
}

.result-title {
  margin: 0 0 8px;
  font-size: 18px;
  letter-spacing: 0;
}

.result-title .el-tag {
  margin-left: 8px;
}

.result-summary {
  margin: 0;
  color: #475569;
}

.confidence-wrap {
  text-align: center;
  flex: 0 0 92px;
}

.confidence-label {
  display: block;
  margin-bottom: 4px;
  color: #64748b;
  font-size: 12px;
}

.result-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 14px;
  margin: 14px 0;
}

.risk-card {
  margin-top: 14px;
}

.risk-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.risk-main {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.risk-score {
  font-weight: 600;
  color: #155e75;
}

.risk-review-tip {
  color: #b45309;
  font-size: 12px;
}

.factor-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 8px;
  margin-bottom: 10px;
}

.factor-item {
  display: flex;
  justify-content: space-between;
  padding: 6px 8px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 12px;
}

.factor-label {
  color: #64748b;
}

.factor-value {
  font-weight: 600;
}

.rule-list {
  margin: 0 0 6px;
  padding-left: 18px;
  color: #475569;
  font-size: 12px;
}

.risk-version {
  margin: 0;
  color: #94a3b8;
  font-size: 12px;
}

.model-comparison-card {
  margin-top: 14px;
}

.disagreement-viz-card {
  margin-top: 14px;
}

.result-card {
  min-width: 0;
}

.result-card h4 {
  margin: 10px 0 6px;
  color: #334155;
}

.action-list {
  margin: 0;
  padding-left: 18px;
  color: #475569;
}

.action-list li {
  margin-bottom: 6px;
}

.evidence-card {
  margin-top: 14px;
}

.evidence-item {
  padding: 12px 0;
  border-bottom: 1px solid #eef2f7;
}

.evidence-item:last-child {
  border-bottom: 0;
}

.evidence-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.evidence-source {
  font-weight: 600;
  color: #155e75;
}

.evidence-score {
  color: #64748b;
  white-space: nowrap;
}

.evidence-text {
  margin: 6px 0;
  color: #475569;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.evidence-judge-card {
  margin-top: 14px;
}

.evidence-judge-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.judge-finding {
  padding: 10px 0;
  border-bottom: 1px solid #eef2f7;
}

.judge-finding:last-child {
  border-bottom: 0;
}

.judge-finding-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.finding-category {
  font-weight: 600;
  color: #334155;
}

.support-score {
  color: #64748b;
  font-size: 12px;
}

.evidence-ids {
  margin-top: 6px;
  color: #475569;
  font-size: 13px;
  word-break: break-all;
}

.unsupported-list {
  margin: 6px 0 0;
  padding-left: 18px;
  color: #b45309;
  font-size: 13px;
}

.location-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 6px;
}

.location-chip {
  padding: 3px 8px;
  border: 1px solid #dbeafe;
  border-radius: 4px;
  background: #eff6ff;
  color: #1e40af;
  font-size: 12px;
}

.judge-counts {
  margin: 10px 0 0;
  color: #64748b;
  font-size: 13px;
}

.footer-actions {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 18px;
}

.human-review-card {
  margin-top: 14px;
}

.human-review-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.human-review-reasons {
  margin: 0 0 10px;
  padding-left: 18px;
  color: #b45309;
  font-size: 13px;
}

.human-review-reasons li {
  margin-bottom: 4px;
}

.human-resolution {
  margin-bottom: 10px;
  padding: 10px 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  color: #475569;
  font-size: 13px;
}

.human-resolution p {
  margin: 0 0 4px;
}

.human-resolution p:last-child {
  margin-bottom: 0;
}

.rect-card {
  margin-top: 14px;
}

.evidence-chain-card {
  margin-top: 14px;
}

.hazard-overlay-card {
  margin-top: 14px;
}

.rect-steps {
  margin-bottom: 12px;
}

.rect-history {
  margin-bottom: 12px;
  padding: 10px 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}

.rect-history h4 {
  margin: 0 0 8px;
  color: #334155;
  font-size: 13px;
}

.rect-history ul {
  margin: 0;
  padding-left: 16px;
  color: #475569;
  font-size: 12px;
}

.rect-history li {
  margin-bottom: 4px;
}

.rect-history-meta {
  margin-left: 6px;
  color: #94a3b8;
}

.rect-history-note {
  display: block;
  color: #64748b;
}

.rect-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.compare-grid {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-bottom: 12px;
}

.compare-pair {
  padding: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}

.compare-pair-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  color: #334155;
  font-size: 13px;
  font-weight: 600;
}

.compare-pair-status {
  color: #64748b;
  font-size: 12px;
  font-weight: 400;
}

.compare-columns {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.compare-column {
  min-width: 0;
}

.compare-missing {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 78px;
  border: 1px dashed #cbd5e1;
  border-radius: 6px;
  color: #94a3b8;
  font-size: 12px;
}

.compare-unmatched {
  margin: 0 0 10px;
  padding: 8px 10px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 6px;
  color: #b45309;
  font-size: 12px;
}

.compare-empty {
  margin-bottom: 12px;
}

.original-only {
  margin-bottom: 12px;
}

.compare-label {
  margin-bottom: 6px;
  color: #64748b;
  font-size: 12px;
}

.thumb-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.thumb {
  width: 104px;
  height: 78px;
  border-radius: 6px;
}

.rect-note {
  margin: 0 0 10px;
  color: #475569;
}

.compare-result {
  margin-bottom: 12px;
  padding: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.completion-box {
  margin-top: 10px;
  padding: 10px 12px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}

.completion-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

.completion-conf {
  color: #64748b;
  font-size: 12px;
}

.completion-reasons {
  margin: 8px 0 0;
  padding-left: 16px;
  color: #475569;
  font-size: 12px;
}

.completion-reasons li {
  margin-bottom: 4px;
}

.completion-version {
  margin: 8px 0 0;
  color: #94a3b8;
  font-size: 12px;
}

.compare-result-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
  font-weight: 600;
}

.compare-score {
  color: #155e75;
}

.compare-summary {
  margin: 8px 0 0;
  color: #475569;
}

.issue-list {
  margin: 8px 0 0;
  padding-left: 18px;
  color: #b45309;
}

.rect-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.rect-actions {
  display: flex;
  gap: 10px;
}

.disclaimer {
  color: #94a3b8;
  font-size: 12px;
}

@media (max-width: 640px) {
  .result-header {
    flex-direction: column;
  }

  .confidence-wrap {
    align-self: flex-start;
    text-align: left;
  }
}
</style>
