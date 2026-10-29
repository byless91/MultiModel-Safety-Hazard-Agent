<template>
  <section class="page">
    <h1 class="page-title">现场隐患智能研判</h1>
    <p class="page-subtitle">
      上传现场照片并描述情况，系统给出隐患类型、风险等级和处置建议。
    </p>

    <el-card v-loading="busy" class="intake-card">
      <form class="intake" @submit.prevent="submit">
        <div class="intake-row">
          <div class="field">
            <label class="field-label">
              现场照片
              <span class="field-hint">最多 3 张，也可以先只用文字描述</span>
            </label>
            <el-upload
              v-model:file-list="fileList"
              list-type="picture-card"
              accept="image/*"
              multiple
              :auto-upload="false"
              :limit="3"
              :on-exceed="onExceed"
              :disabled="store.hasPendingSubmission"
            >
              <el-icon><Plus /></el-icon>
            </el-upload>
          </div>

          <div class="field">
            <label class="field-label" for="hazard-description">
              情况描述
              <span class="field-hint">写清位置、看到的物品和危险情况</span>
            </label>
            <el-input
              id="hazard-description"
              v-model="description"
              type="textarea"
              :rows="4"
              :disabled="store.hasPendingSubmission"
              placeholder="例如：3 栋 2 单元楼道堆满纸箱，挡住疏散通道"
            />
          </div>
        </div>

        <div class="intake-actions">
          <el-button
            type="primary"
            native-type="submit"
            :loading="busy || working"
            :disabled="!description.trim() || store.hasPendingSubmission"
          >
            <el-icon><UploadFilled /></el-icon>
            开始研判
          </el-button>
          <el-button :disabled="store.loading || store.submissionBusy" @click="resetForm">
            {{ store.hasPendingSubmission ? '新建研判' : '重置' }}
          </el-button>
          <span v-if="!description.trim()" class="action-hint">填写情况描述后才能开始</span>
        </div>
      </form>
    </el-card>

    <section v-if="store.hasPendingSubmission" class="submission-recovery" role="status" aria-live="polite">
      <p>{{ store.submission?.phase === 'failed' ? '本次研判未完成，原记录已保留。' : '结果尚未确认，请先查询本次提交。' }}</p>
      <div class="intake-actions">
        <el-button :disabled="store.submissionBusy" @click="resumeSubmission(false)">查询本次提交</el-button>
        <el-button v-if="store.canRetrySubmission" :disabled="store.submissionBusy" @click="resumeSubmission(true)">
          重试原内容
        </el-button>
        <RouterLink v-if="store.submission?.assessmentId" :to="`/assessments/${store.submission.assessmentId}`">
          查看研判记录
        </RouterLink>
        <RouterLink to="/history">历史记录</RouterLink>
      </div>
      <p class="field-hint">刷新后仍可查询。新建研判不会取消已受理的请求。</p>
    </section>

    <JobProgress :assessment="assessment" :job="job" :busy="busy" :waiting="waiting" :notice="notice"
      :working="working" @resume="session.resume" />
    <el-alert v-if="error" class="error-alert" :title="error" type="error" :closable="false" show-icon />
    <section v-if="assessment" class="result-panel">
      <div class="result-panel-head">
        <span class="result-panel-title">研判结果</span>
        <span class="result-id">记录号 {{ assessment.id.slice(0, 8) }}</span>
      </div>
      <AssessmentResult
        :assessment="assessment"
        :loading="busy || working"
        @followup="onFollowup"
        @updated="onUpdated"
      />
    </section>
  </section>
</template>

<script setup lang="ts">
import { ElMessage, type UploadFile } from 'element-plus'
import { ref } from 'vue'

import AssessmentResult from '../components/AssessmentResult.vue'
import { useAssessmentStore } from '../stores/assessment'
import JobProgress from '../components/JobProgress.vue'
import { useAssessmentSession } from '../composables/useAssessmentSession'
import type { Assessment } from '../types'

const store = useAssessmentStore()
const description = ref('')
const fileList = ref<UploadFile[]>([])
const session = useAssessmentSession()
const { assessment, job, busy, working, waiting, notice, error } = session

async function submit() {
  if (!description.value.trim()) return
  const files = fileList.value
    .map((item) => (item.raw ? item.raw : (item as unknown as File)))
    .filter((item) => item instanceof File)
  await session.run((signal) => store.create(description.value.trim(), files, { wait: false, signal }))
}

async function resumeSubmission(retry: boolean) {
  await session.run((signal) => retry
    ? store.retryCreate({ wait: false, signal }) : store.recoverCreate({ wait: false, signal }))
}

async function onFollowup(answer: string) {
  if (!assessment.value) return
  const id = assessment.value.id
  await session.run((signal) => store.followup(id, answer, { wait: false, signal }))
}

function onUpdated(updated: Assessment) {
  session.update(updated)
}
function resetForm() {
  session.clear()
  store.startNewSubmission()
  description.value = ''
  fileList.value = []
  assessment.value = null
  store.error = ''
}

function onExceed() {
  ElMessage.warning('最多上传 3 张图片')
}
</script>

<style scoped>
.intake-card {
  background: var(--panel);
}

.submission-recovery {
  margin-top: var(--s-4);
  padding: var(--s-4);
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel);
}

.intake {
  display: flex;
  flex-direction: column;
  gap: var(--s-5);
}

.intake-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr);
  gap: var(--s-5);
  align-items: start;
}

.field {
  min-width: 0;
}

.field-label {
  display: flex;
  align-items: baseline;
  gap: var(--s-2);
  margin-bottom: var(--s-2);
  font-weight: 600;
  color: var(--text-strong);
}

.field-hint {
  font-weight: 400;
  font-size: var(--fs-xs);
  color: var(--muted);
}

.intake-actions {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  padding-top: var(--s-4);
  border-top: 1px solid var(--border);
}

.action-hint {
  color: var(--muted);
  font-size: var(--fs-xs);
}

.error-alert {
  margin-top: var(--s-4);
}

.result-panel {
  margin-top: var(--s-5);
  padding: var(--s-4);
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--r-card);
}

.result-panel-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: var(--s-3);
  padding-bottom: var(--s-3);
  border-bottom: 1px solid var(--border);
}

.result-panel-title {
  font-weight: 700;
  color: var(--text-strong);
}

.result-id {
  color: var(--muted);
  font-size: var(--fs-xs);
}

@media (max-width: 860px) {
  .intake-row {
    grid-template-columns: 1fr;
  }
}
</style>
