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

      <el-alert
        v-if="assessment.status === 'needs_review'"
        title="该结果需要人工复核"
        type="warning"
        :closable="false"
        show-icon
      />

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
          <span>参考依据（{{ report.evidence_count }}）</span>
        </template>
        <el-empty v-if="!report.legal_basis.length" description="暂无检索到知识库依据" />
        <div v-for="item in report.legal_basis" :key="item.source + item.text" class="evidence-item">
          <div class="evidence-head">
            <span class="evidence-source">{{ item.source }}</span>
            <span class="evidence-score">相关度 {{ Math.round(item.score * 100) }}%</span>
          </div>
          <p class="evidence-text">{{ item.text }}</p>
          <div class="tag-row">
            <el-tag v-for="tag in item.tags" :key="tag" size="small" type="info">{{ tag }}</el-tag>
          </div>
        </div>
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
        <div v-if="originals.length || rectImages.length" class="compare-grid">
          <div>
            <div class="compare-label">整改前</div>
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
          <div>
            <div class="compare-label">整改后</div>
            <div class="thumb-row">
              <template v-for="img in rectImages" :key="img.id">
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
        </div>
        <div class="rect-form">
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
          <div class="rect-actions">
            <el-button type="primary" :loading="store.loading" @click="onSubmitRectification">
              提交整改照片
            </el-button>
            <el-button v-if="rectImages.length" @click="onRecompare">
              <el-icon><RefreshRight /></el-icon>
              重新 AI 比对
            </el-button>
            <el-button
              v-if="assessment.rectification_status === 'under_review'"
              type="success"
              @click="onConfirmRectification"
            >
              确认整改完成
            </el-button>
          </div>
        </div>
      </el-card>

      <div class="footer-actions">
        <el-button @click="onDownload">
          <el-icon><Download /></el-icon>
          下载报告
        </el-button>
        <el-button type="primary" :disabled="assessment.confirmed" @click="emit('confirm')">
          <el-icon><CircleCheck /></el-icon>
          {{ assessment.confirmed ? '已人工确认' : '确认结果并定稿' }}
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
import type { Assessment } from '../types'

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

const originals = computed(() =>
  props.assessment.images.filter((image) => image.image_kind === 'original'),
)
const rectImages = computed(() =>
  props.assessment.images.filter((image) => image.image_kind === 'rectification'),
)

const rectTag = computed<'success' | 'warning' | 'info'>(() => {
  const status = props.assessment.rectification_status
  return status === 'resolved' ? 'success' : status === 'under_review' ? 'warning' : 'info'
})

const rectLabel = computed(() => {
  const status = props.assessment.rectification_status
  return status === 'resolved' ? '已整改完成' : status === 'under_review' ? '整改待复核' : '未提交'
})

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

async function onConfirmRectification() {
  const updated = await store.confirmRectification(props.assessment.id, true)
  emit('updated', updated)
  ElMessage.success('已确认整改完成')
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

.footer-actions {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 18px;
}

.rect-card {
  margin-top: 14px;
}

.rect-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.compare-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 14px;
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
