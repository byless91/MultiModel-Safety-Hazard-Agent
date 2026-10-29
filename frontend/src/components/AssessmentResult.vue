<template>
  <div v-loading="loading" class="result-wrap">
    <section v-if="showRecordMeta" class="record-meta" aria-label="位置与来源">
      <dl>
        <div><dt>数据来源</dt><dd>{{ dataSourceLabel }}</dd></div>
        <div><dt>事件时间</dt><dd>{{ assessment.event_time ? formatTime(assessment.event_time) : '未填写' }}</dd></div>
        <div><dt>录入时间</dt><dd>{{ formatTime(assessment.created_at) }}</dd></div>
        <div><dt>位置精度</dt><dd>{{ precisionLabel }}</dd></div>
        <div v-if="assessment.address"><dt>地址</dt><dd>{{ assessment.address }}</dd></div>
        <div v-if="assessment.district"><dt>区划</dt><dd>{{ assessment.district }}</dd></div>
        <div v-if="assessment.facility || assessment.scene">
          <dt>设施 / 场景</dt>
          <dd>{{ [assessment.facility, assessment.scene].filter(Boolean).join(' · ') }}</dd>
        </div>
        <div v-if="assessment.latitude !== null && assessment.latitude !== undefined">
          <dt>坐标</dt>
          <dd>{{ assessment.latitude }}, {{ assessment.longitude }} · {{ coordinateSystemLabel }} · {{ coordinateSourceLabel }}</dd>
        </div>
        <div v-if="assessment.import_batch_id">
          <dt>导入批次</dt>
          <dd>{{ assessment.import_batch_id }} · 外部编号 {{ assessment.source_ref || '未填写' }}</dd>
        </div>
      </dl>
    </section>
    <p v-if="assessment.record_mode === 'imported'" class="import-note">
      导入记录：仅保留位置、来源和时间信息，未做 AI 研判。
    </p>
    <ClassificationPanel v-if="assessment.record_mode === 'classification'" :assessment="assessment"
      :loading="loading" @updated="emit('updated', $event)" @download="onDownload" />
    <el-alert
      v-else-if="assessment.status === 'needs_more_info'"
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
          <p class="review-source">{{ assessment.confirmed ? '人工最终结论' : report.result_source === 'human_review' ? '人工复核意见，尚未定稿' : 'AI 原始建议，需结合现场核实' }}</p>
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

          <HumanReviewPanel :assessment="assessment" :loading="loading" @updated="emit('updated', $event)" />
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
            <h4 class="block-title">AI / 规则原始风险计算</h4>
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

          <RectificationPanel
            :assessment="assessment"
            @updated="emit('updated', $event)"
          />
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
    <p v-else class="report-empty">
      {{ assessment.status === 'failed' ? '本次研判未生成报告，失败原因见上方任务状态。原记录已保留。'
        : assessment.status === 'pending' || assessment.status === 'processing' ? '报告生成中，可从上方查看任务状态。'
          : '当前记录暂无报告，可重新查询记录。' }}
    </p>
  </div>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onMounted, onUnmounted, ref } from 'vue'

import { useAssessmentStore } from '../stores/assessment'
import type { Assessment, FindingLocation } from '../types'
import { rectStatusLabel } from '../constants/rectification'
import HumanReviewPanel from './HumanReviewPanel.vue'
import ClassificationPanel from './ClassificationPanel.vue'
import { extractError } from '../utils/errors'
import { formatTime } from '../utils/format'
import EvidenceChain from './EvidenceChain.vue'
import RectificationPanel from './RectificationPanel.vue'
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
  updated: [assessment: Assessment]
}>()

const rectLabel = computed(() => rectStatusLabel(props.assessment.rectification_status))

const DATA_SOURCE_LABELS: Record<string, string> = {
  report: '现场上报', public_case: '公开案例', simulated: '模拟数据',
}
const PRECISION_LABELS: Record<string, string> = {
  coordinate: '坐标级', address: '地址级', district: '区划级', unknown: '未提供',
}
const COORDINATE_SYSTEM_LABELS: Record<string, string> = {
  wgs84: 'WGS84', gcj02: 'GCJ-02', bd09: 'BD-09',
}
const COORDINATE_SOURCE_LABELS: Record<string, string> = { manual: '手工填写', import: '导入' }

const hasCoordinates = computed(() => props.assessment.latitude !== null && props.assessment.latitude !== undefined)
const showRecordMeta = computed(() => props.assessment.record_mode === 'imported'
  || Boolean(props.assessment.data_source || props.assessment.event_time || props.assessment.address
    || props.assessment.district || props.assessment.facility || props.assessment.scene) || hasCoordinates.value)
const dataSourceLabel = computed(() => DATA_SOURCE_LABELS[props.assessment.data_source || ''] || '未标注')
const precisionLabel = computed(() => PRECISION_LABELS[props.assessment.location_precision || 'unknown'] || '未提供')
const coordinateSystemLabel = computed(() => COORDINATE_SYSTEM_LABELS[props.assessment.coordinate_system || ''] || '坐标系未标注')
const coordinateSourceLabel = computed(() => COORDINATE_SOURCE_LABELS[props.assessment.coordinate_source || ''] || '来源未标注')

const answer = ref('')
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

async function onDownload() {
  try {
    const { filename, content } = await store.downloadReport(props.assessment.id)
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.click()
    URL.revokeObjectURL(url)
  } catch (err) {
    ElMessage.error(extractError(err))
  }
}

</script>

<style scoped>
.result-wrap {
  min-height: 120px;
}

.record-meta {
  padding: 10px 12px;
  margin-bottom: 12px;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 6px;
}

.record-meta dl {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr));
  gap: 6px 16px;
  margin: 0;
}

.record-meta div {
  display: flex;
  gap: 6px;
  min-width: 0;
}

.record-meta dt {
  color: var(--muted);
  font-size: 12px;
  white-space: nowrap;
}

.record-meta dd {
  margin: 0;
  font-size: 13px;
  overflow-wrap: anywhere;
}

.import-note {
  padding: 8px 12px;
  margin: 0 0 12px;
  color: var(--muted);
  font-size: 13px;
  background: var(--surface-1);
  border: 1px dashed var(--border);
  border-radius: 6px;
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

.review-source {
  color: var(--muted);
  font-size: var(--fs-sm);
  margin: var(--s-2) 0 0;
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
  color: var(--text-strong);
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
  background: var(--warning-soft);
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
  background: var(--warning-soft);
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
