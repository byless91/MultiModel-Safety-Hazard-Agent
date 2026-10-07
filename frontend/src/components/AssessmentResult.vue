<template>
  <div v-loading="loading" class="result-wrap">
    <el-alert
      v-if="assessment.status === 'needs_more_info'"
      title="还需要补充现场情况"
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
      <header class="conclusion">
        <div class="conclusion-main">
          <h3 class="conclusion-title">
            {{ assessment.hazard_category || '隐患类型待确认' }}
            <el-tag :type="levelTag" effect="dark" size="small">{{ levelLabel }}</el-tag>
          </h3>
          <p class="conclusion-text">{{ report.summary }}</p>
        </div>
        <div class="conclusion-metric">
          <span class="conclusion-metric-value">{{ confidencePercent }}%</span>
          <span class="conclusion-metric-label">AI 把握</span>
        </div>
      </header>

      <dl class="plain-summary">
        <div class="plain-item">
          <dt>风险等级</dt>
          <dd>{{ riskDesc }}</dd>
        </div>
        <div class="plain-item">
          <dt>法规依据</dt>
          <dd>{{ evidenceText }}</dd>
        </div>
        <div class="plain-item plain-item--wide">
          <dt>下一步</dt>
          <dd class="next-step">{{ nextStepText }}</dd>
        </div>
      </dl>

      <el-alert
        v-if="assessment.status === 'needs_review'"
        class="review-alert"
        title="该结果需要人工复核后才能使用"
        type="warning"
        :closable="false"
        show-icon
      />

      <el-tabs v-model="activeTab" class="result-tabs">
        <el-tab-pane label="处置意见" name="action">
          <section class="block">
            <h4 class="block-title">处置建议</h4>
            <div class="advice-grid">
              <div>
                <h5 class="advice-title">现场处置</h5>
                <ul class="action-list">
                  <li v-for="action in report.immediate_actions" :key="action">{{ action }}</li>
                </ul>
              </div>
              <div>
                <h5 class="advice-title">长效机制</h5>
                <ul class="action-list">
                  <li v-for="action in report.long_term_actions" :key="action">{{ action }}</li>
                </ul>
              </div>
            </div>
          </section>

          <section class="block">
            <h4 class="block-title">整改工单</h4>
            <el-descriptions :column="workOrderColumns" size="small" border>
              <el-descriptions-item label="类别">{{ report.work_order.category }}</el-descriptions-item>
              <el-descriptions-item label="等级">{{ report.work_order.level }}</el-descriptions-item>
              <el-descriptions-item label="时限">{{ report.work_order.deadline }}</el-descriptions-item>
              <el-descriptions-item label="位置">{{ report.work_order.location }}</el-descriptions-item>
              <el-descriptions-item label="验收" :span="workOrderColumns">
                {{ report.work_order.acceptance }}
              </el-descriptions-item>
            </el-descriptions>
          </section>

          <section v-if="humanReviewVisible" class="block">
            <h4 class="block-title">
              人工复核
              <el-tag
                :type="assessment.confirmed ? 'success' : assessment.status === 'needs_review' ? 'warning' : 'primary'"
                effect="light"
                size="small"
              >
                {{ humanReviewTagLabel }}
              </el-tag>
            </h4>
            <ul v-if="assessment.review_reasons?.length" class="review-reasons">
              <li v-for="reason in assessment.review_reasons" :key="reason">{{ reason }}</li>
            </ul>
            <div v-if="humanResolution" class="resolution">
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
          </section>
        </el-tab-pane>
        <el-tab-pane name="evidence">
          <template #label>
            证据依据
            <span
              v-if="assessment.evidence.length"
              class="tab-badge"
              :class="{ 'tab-badge--warn': evidenceNeedsAttention }"
            >
              {{ assessment.evidence.length }}
            </span>
          </template>

          <section class="block">
            <h4 class="block-title">法规证据</h4>
            <LegalEvidence :assessment="assessment" />
          </section>

          <section
            v-if="assessment.evidence_judge || assessment.findings?.length"
            class="block"
          >
            <h4 class="block-title">
              证据链判定
              <el-tag
                v-if="assessment.evidence_judge"
                :type="assessment.evidence_judge.supported ? 'success' : 'warning'"
                effect="light"
                size="small"
              >
                {{ assessment.evidence_judge.supported ? '证据支持' : '证据不足' }}
              </el-tag>
            </h4>
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
          </section>

          <section class="block">
            <h4 class="block-title">证据链</h4>
            <EvidenceChain :assessment="assessment" />
          </section>

          <section class="block">
            <h4 class="block-title">隐患定位（可选 Bounding Box）</h4>
            <HazardOverlay :assessment="assessment" />
          </section>
        </el-tab-pane>
        <el-tab-pane label="模型分析" name="model">
          <section
            v-if="
              (assessment.risk_score !== undefined && assessment.risk_score !== null) ||
              assessment.risk_result
            "
            class="block"
          >
            <h4 class="block-title">风险引擎判定与解释</h4>
            <RiskExplanation :assessment="assessment" />
          </section>

          <section class="block">
            <h4 class="block-title">模型 A/B 对比</h4>
            <ModelComparison :assessment="assessment" />
          </section>

          <section v-if="assessment.disagreement" class="block">
            <h4 class="block-title">分歧可视化</h4>
            <DisagreementViz :assessment="assessment" />
          </section>
        </el-tab-pane>

        <el-tab-pane name="rectification">
          <template #label>
            整改闭环
            <span v-if="assessment.rectification_status" class="tab-badge">
              {{ rectLabel }}
            </span>
          </template>

          <section class="block">
            <h4 class="block-title">整改回传</h4>
            <el-steps
              v-if="assessment.rectification_status"
              :active="rectActiveIndex"
              finish-status="success"
              class="rect-steps"
              simple
            >
              <el-step v-for="step in rectSteps" :key="step.value" :title="step.label" />
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
                  <div>
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
                  <div>
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
                :stroke-width="8"
                :color="rectColor"
              />
              <p v-if="assessment.rectification_analysis?.summary" class="compare-summary">
                {{ assessment.rectification_analysis.summary }}
              </p>
              <ul v-if="assessment.rectification_analysis?.issues?.length" class="issue-list">
                <li v-for="issue in assessment.rectification_analysis.issues" :key="issue">
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
              <h5 class="advice-title">整改流程记录</h5>
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
          </section>
        </el-tab-pane>
      </el-tabs>

      <footer class="result-footer">
        <el-button @click="onDownload">
          <el-icon><Download /></el-icon>
          下载报告
        </el-button>
        <span class="disclaimer">{{ report.disclaimer }}</span>
      </footer>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ElMessage, type UploadFile } from 'element-plus'
import { computed, onMounted, onUnmounted, ref } from 'vue'

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
const activeTab = ref('action')
const narrow = ref(false)
let mediaQuery: MediaQueryList | null = null

function syncNarrow(event?: MediaQueryListEvent) {
  narrow.value = event ? event.matches : Boolean(mediaQuery?.matches)
}

onMounted(() => {
  mediaQuery = window.matchMedia('(max-width: 720px)')
  syncNarrow()
  mediaQuery.addEventListener('change', syncNarrow)
})

onUnmounted(() => {
  mediaQuery?.removeEventListener('change', syncNarrow)
})

const workOrderColumns = computed(() => (narrow.value ? 1 : 2))
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
  return score >= 0.8 ? '#15803d' : score >= 0.5 ? '#b45309' : '#94a3b8'
})

const levelTag = computed<'danger' | 'warning' | 'success'>(() => {
  const level = props.assessment.risk_level || 3
  return level === 1 ? 'danger' : level === 2 ? 'warning' : 'success'
})

const levelLabel = computed(() => {
  const level = props.assessment.risk_level
  return level === 1 ? '一级 · 立即处置' : level === 2 ? '二级 · 限期整改' : '三级 · 建议改进'
})

const confidencePercent = computed(() =>
  Math.round((props.assessment.confidence || 0) * 100),
)

const riskDesc = computed(() => {
  const level = props.assessment.risk_level || 3
  if (level === 1) return '高风险 · 应立即处置'
  if (level === 2) return '中风险 · 尽快整改'
  return '较低风险 · 建议改进'
})

const evidenceText = computed(() => {
  const judge = props.assessment.evidence_judge
  if (judge && judge.supported) return '找到法规依据，可支撑结论'
  if (judge && judge.unsupported_claims?.length) return '法规依据不足，需现场核实'
  if (props.assessment.evidence.length) return '已列出参考资料，请结合现场判断'
  return '暂无参考资料，需现场核实'
})

const evidenceNeedsAttention = computed(
  () => Boolean(props.assessment.evidence_judge && !props.assessment.evidence_judge.supported),
)

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

/* Conclusion: one screen answers what it is, how sure, what next. */
.conclusion {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s-5);
  padding-bottom: var(--s-4);
  border-bottom: 1px solid var(--border);
}

.conclusion-main {
  min-width: 0;
}

.conclusion-title {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  margin: 0 0 var(--s-2);
  font-size: var(--fs-lg);
  font-weight: 700;
  color: var(--text-strong);
}

.conclusion-text {
  margin: 0;
  max-width: 68ch;
  color: var(--text);
}

.conclusion-metric {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  flex: none;
}

.conclusion-metric-value {
  font-size: var(--fs-2xl);
  font-weight: 700;
  line-height: 1.1;
  color: var(--brand);
  font-variant-numeric: tabular-nums;
}

.conclusion-metric-label {
  margin-top: var(--s-1);
  font-size: var(--fs-xs);
  color: var(--muted);
}

.plain-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s-3) var(--s-5);
  margin: var(--s-4) 0;
  padding: 0;
}

.plain-summary .plain-item {
  min-width: 0;
}

.plain-item--wide {
  grid-column: 1 / -1;
}

.plain-summary dt {
  font-size: var(--fs-xs);
  color: var(--muted);
}

.plain-summary dd {
  margin: var(--s-1) 0 0;
  color: var(--text);
}

.plain-summary dd.next-step {
  color: var(--brand-dark);
  font-weight: 600;
}

.review-alert {
  margin-bottom: var(--s-4);
}

.result-tabs {
  margin-top: var(--s-2);
}

.tab-badge {
  display: inline-block;
  margin-left: var(--s-1);
  padding: 0 6px;
  border-radius: var(--r-pill);
  background: var(--panel-2);
  color: var(--muted);
  font-size: var(--fs-xs);
  line-height: 18px;
}

.tab-badge--warn {
  background: #fef3c7;
  color: var(--warning);
}

/* Flat sections: no nested cards, separation comes from space and a rule. */
.block {
  padding: var(--s-4) 0;
  border-bottom: 1px solid var(--border);
}

.block:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}

.block-title {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  margin: 0 0 var(--s-3);
  font-size: var(--fs-md);
  font-weight: 700;
  color: var(--text-strong);
}

.advice-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s-5);
}

.advice-title {
  margin: 0 0 var(--s-2);
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--muted);
}

.action-list {
  margin: 0;
  padding-left: 18px;
  color: var(--text);
}

.action-list li {
  margin-bottom: var(--s-1);
}

.review-reasons {
  margin: 0 0 var(--s-3);
  padding-left: 18px;
  color: var(--warning);
  font-size: var(--fs-sm);
}

.review-reasons li {
  margin-bottom: var(--s-1);
}

.resolution {
  margin-bottom: var(--s-3);
  padding: var(--s-3);
  border-radius: var(--r-control);
  background: var(--panel-2);
  color: var(--text);
  font-size: var(--fs-sm);
}

.resolution p {
  margin: 0 0 var(--s-1);
}

.resolution p:last-child {
  margin-bottom: 0;
}

.judge-finding {
  padding: var(--s-3) 0;
  border-bottom: 1px solid var(--border);
}

.judge-finding:last-of-type {
  border-bottom: 0;
}

.judge-finding-head {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  flex-wrap: wrap;
}

.finding-category {
  font-weight: 600;
  color: var(--text-strong);
}

.support-score {
  color: var(--muted);
  font-size: var(--fs-xs);
}

.evidence-ids {
  margin-top: var(--s-1);
  color: var(--muted);
  font-size: var(--fs-sm);
  word-break: break-all;
}

.unsupported-list {
  margin: var(--s-1) 0 0;
  padding-left: 18px;
  color: var(--warning);
  font-size: var(--fs-sm);
}

.location-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s-2);
  margin-top: var(--s-2);
}

.location-chip {
  padding: 2px 8px;
  border-radius: var(--r-pill);
  background: var(--brand-soft);
  color: var(--brand-dark);
  font-size: var(--fs-xs);
}

.judge-counts {
  margin: var(--s-3) 0 0;
  color: var(--muted);
  font-size: var(--fs-sm);
}

.rect-steps {
  margin-bottom: var(--s-4);
}

.compare-grid {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
  margin-bottom: var(--s-3);
}

.compare-pair {
  padding: var(--s-3);
  border: 1px solid var(--border);
  border-radius: var(--r-control);
}

.compare-pair-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--s-2);
  color: var(--text-strong);
  font-size: var(--fs-sm);
  font-weight: 600;
}

.compare-pair-status {
  color: var(--muted);
  font-size: var(--fs-xs);
  font-weight: 400;
}

.compare-columns {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--s-3);
}

.compare-label {
  margin-bottom: var(--s-1);
  color: var(--muted);
  font-size: var(--fs-xs);
}

.compare-missing {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 78px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--r-control);
  color: var(--muted);
  font-size: var(--fs-xs);
}

.compare-unmatched {
  margin: 0 0 var(--s-3);
  padding: var(--s-2) var(--s-3);
  border-radius: var(--r-control);
  background: #fffbeb;
  color: var(--warning);
  font-size: var(--fs-sm);
}

.compare-empty,
.original-only {
  margin-bottom: var(--s-3);
}

.thumb-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s-2);
}

.thumb {
  width: 104px;
  height: 78px;
  border-radius: var(--r-control);
}

.rect-note {
  margin: 0 0 var(--s-3);
  color: var(--text);
}

.compare-result {
  margin-bottom: var(--s-3);
  padding: var(--s-3);
  border: 1px solid var(--border);
  border-radius: var(--r-control);
}

.compare-result-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--s-2);
  font-weight: 600;
}

.compare-score {
  color: var(--brand);
  font-variant-numeric: tabular-nums;
}

.compare-summary {
  margin: var(--s-2) 0 0;
  color: var(--text);
}

.issue-list {
  margin: var(--s-2) 0 0;
  padding-left: 18px;
  color: var(--warning);
}

.completion-box {
  margin-top: var(--s-3);
  padding-top: var(--s-3);
  border-top: 1px solid var(--border);
}

.completion-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--s-2);
}

.completion-conf {
  color: var(--muted);
  font-size: var(--fs-xs);
}

.completion-reasons {
  margin: var(--s-2) 0 0;
  padding-left: 18px;
  color: var(--text);
  font-size: var(--fs-sm);
}

.completion-reasons li {
  margin-bottom: var(--s-1);
}

.completion-version {
  margin: var(--s-2) 0 0;
  color: var(--muted);
  font-size: var(--fs-xs);
}

.rect-history {
  margin-bottom: var(--s-3);
}

.rect-history ul {
  margin: 0;
  padding-left: 18px;
  color: var(--text);
  font-size: var(--fs-sm);
}

.rect-history li {
  margin-bottom: var(--s-1);
}

.rect-history-meta {
  margin-left: var(--s-1);
  color: var(--muted);
}

.rect-history-note {
  display: block;
  color: var(--muted);
}

.rect-form {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
  margin-bottom: var(--s-3);
}

.rect-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s-2);
}

.result-footer {
  display: flex;
  align-items: center;
  gap: var(--s-4);
  margin-top: var(--s-5);
  padding-top: var(--s-4);
  border-top: 1px solid var(--border);
}

.disclaimer {
  color: var(--muted);
  font-size: var(--fs-xs);
}

.followup-box {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
}

.question-list {
  margin: 0;
  padding-left: 18px;
}

.followup-button {
  align-self: flex-start;
}

@media (max-width: 720px) {
  .conclusion {
    flex-direction: column;
    gap: var(--s-3);
  }

  .conclusion-metric {
    align-items: flex-start;
  }

  .plain-summary,
  .advice-grid,
  .compare-columns {
    grid-template-columns: 1fr;
  }

  .result-footer {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
