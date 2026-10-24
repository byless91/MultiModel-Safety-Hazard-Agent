<template>
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
</template>

<script setup lang="ts">
import { ElMessage, type UploadFile } from 'element-plus'
import { computed, ref } from 'vue'

import { useAssessmentStore } from '../stores/assessment'
import type { Assessment } from '../types'
import {
  RECT_LABELS,
  RECT_STEPS,
  VERDICT_LABELS,
} from '../constants/rectification'
import { formatTime } from '../utils/format'
import { extractError } from '../utils/errors'

const props = defineProps<{
  assessment: Assessment
}>()

const emit = defineEmits<{
  updated: [assessment: Assessment]
}>()

const store = useAssessmentStore()
const rectFiles = ref<UploadFile[]>([])
const rectNote = ref('')

const rectImages = computed(() =>
  props.assessment.images
    .filter((image) => image.image_kind === 'rectification')
    .sort(byImageTime),
)

const originals = computed(() =>
  props.assessment.images
    .filter((image) => image.image_kind === 'original')
    .sort(byImageTime),
)

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

const comparisonMeta = computed(
  () => props.assessment.rectification_analysis?.comparison ?? null,
)

const completionAssessment = computed(
  () => props.assessment.rectification_analysis?.assessment ?? null,
)

const verdictLabels = VERDICT_LABELS
const rectSteps = RECT_STEPS

const rectActiveIndex = computed(() => {
  const status = props.assessment.rectification_status
  const index = rectSteps.findIndex((item) => item.value === status)
  return index === -1 ? 0 : index
})

const rectHistory = computed(
  () => props.assessment.rectification_meta?.history ?? [],
)

function statusLabel(status: string) {
  return RECT_LABELS[status] || status
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

function byImageTime(
  a: { created_at?: string | null },
  b: { created_at?: string | null },
) {
  return (a.created_at || '').localeCompare(b.created_at || '')
}

async function onSubmitRectification() {
  try {
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
  } catch (err) {
    ElMessage.error(extractError(err))
  }
}

async function onStartRectification() {
  try {
    const updated = await store.transitionRectification(
      props.assessment.id,
      'rectifying',
      '开始整改',
    )
    emit('updated', updated)
    ElMessage.success('已开始整改')
  } catch (err) {
    ElMessage.error(extractError(err))
  }
}

async function onRectificationTransition(toStatus: string, message: string) {
  try {
    const updated = await store.transitionRectification(
      props.assessment.id,
      toStatus,
    )
    emit('updated', updated)
    ElMessage.success(message)
  } catch (err) {
    ElMessage.error(extractError(err))
  }
}

async function onRecompare() {
  try {
    const updated = await store.compareRectification(props.assessment.id)
    emit('updated', updated)
    ElMessage.success('已完成 AI 前后对比')
  } catch (err) {
    ElMessage.error(extractError(err))
  }
}
</script>

<style scoped>
.rect-steps {
  margin-bottom: var(--s-4);
}
</style>
