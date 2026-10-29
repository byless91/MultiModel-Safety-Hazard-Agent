<template>
  <section class="page">
    <h1 class="page-title">现场分类与录入</h1>
    <p class="page-subtitle">
      上传照片、获取类别与标签建议，再由人工核实录入。风险等级由人工选填。
    </p>

    <el-card v-loading="busy" class="intake-card">
      <form class="intake" @submit.prevent="submit">
        <el-radio-group v-model="mode" :disabled="store.hasPendingSubmission" aria-label="录入方式">
          <el-radio-button value="classification">AI 分类助手</el-radio-button>
          <el-radio-button value="manual">仅人工录入</el-radio-button>
        </el-radio-group>
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

        <details class="intake-meta">
          <summary>位置与来源（可选，无地图也能手填）</summary>
          <div class="meta-grid">
            <label class="field">
              <span class="field-label">地址</span>
              <el-input v-model="address" aria-label="地址" :maxlength="512" :disabled="store.hasPendingSubmission"
                placeholder="例如：幸福路 3 号 2 单元" />
            </label>
            <label class="field">
              <span class="field-label">区划</span>
              <el-input v-model="district" aria-label="区划" :maxlength="128" :disabled="store.hasPendingSubmission"
                placeholder="例如：示例区或街道" />
            </label>
            <label class="field">
              <span class="field-label">设施</span>
              <el-input v-model="facility" aria-label="设施" :maxlength="128" :disabled="store.hasPendingSubmission"
                placeholder="例如：居民楼、仓库、加油站" />
            </label>
            <label class="field">
              <span class="field-label">场景</span>
              <el-input v-model="scene" aria-label="场景" :maxlength="128" :disabled="store.hasPendingSubmission"
                placeholder="例如：楼道、施工现场、林区道路" />
            </label>
            <label class="field">
              <span class="field-label">事件时间</span>
              <input v-model="eventTime" aria-label="事件时间" type="datetime-local"
                :disabled="store.hasPendingSubmission" />
            </label>
            <label class="field">
              <span class="field-label">数据来源</span>
              <select v-model="dataSource" aria-label="数据来源" :disabled="store.hasPendingSubmission">
                <option value="report">现场上报</option>
                <option value="public_case">公开案例</option>
                <option value="simulated">模拟数据</option>
              </select>
            </label>
            <label class="field">
              <span class="field-label">纬度</span>
              <input v-model="latitude" aria-label="纬度" type="number" step="0.000001" min="-90" max="90"
                :disabled="store.hasPendingSubmission" placeholder="可留空" />
            </label>
            <label class="field">
              <span class="field-label">经度</span>
              <input v-model="longitude" aria-label="经度" type="number" step="0.000001" min="-180" max="180"
                :disabled="store.hasPendingSubmission" placeholder="可留空" />
            </label>
            <label class="field">
              <span class="field-label">坐标系</span>
              <select v-model="coordinateSystem" aria-label="坐标系" :disabled="!hasCoordinates || store.hasPendingSubmission">
                <option value="wgs84">WGS84</option>
                <option value="gcj02">GCJ-02（高德/腾讯）</option>
                <option value="bd09">BD-09（百度）</option>
              </select>
            </label>
          </div>
          <p v-if="coordinateError" class="field-hint meta-error">{{ coordinateError }}</p>
          <p class="field-hint">坐标留空时仍可录入；事件时间与录入时间分开保存。</p>
        </details>

        <div class="intake-actions">
          <el-button
            type="primary"
            native-type="submit"
            :loading="busy || working"
            :disabled="!description.trim() || Boolean(coordinateError) || store.hasPendingSubmission"
          >
            <el-icon><UploadFilled /></el-icon>
            {{ mode === 'manual' ? '创建人工记录' : '生成分类建议' }}
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
        <span class="result-panel-title">{{ assessment.record_mode === 'classification' ? '分类记录' : assessment.record_mode === 'imported' ? '导入记录' : '研判结果' }}</span>
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
import { computed, ref } from 'vue'

import AssessmentResult from '../components/AssessmentResult.vue'
import { useAssessmentStore } from '../stores/assessment'
import JobProgress from '../components/JobProgress.vue'
import { useAssessmentSession } from '../composables/useAssessmentSession'
import type { Assessment, CoordinateSystem, DataSource, EntryMode, RecordMetadata } from '../types'

const store = useAssessmentStore()
const description = ref('')
const mode = ref<EntryMode>('classification')
const fileList = ref<UploadFile[]>([])
const address = ref(''), district = ref(''), facility = ref(''), scene = ref('')
const latitude = ref<string | number>(''), longitude = ref<string | number>('')
const coordinateSystem = ref<CoordinateSystem>('wgs84')
const dataSource = ref<DataSource>('report')
const eventTime = ref('')
const coordinateText = (value: string | number) => String(value ?? '').trim()
const hasCoordinates = computed(() => Boolean(coordinateText(latitude.value) || coordinateText(longitude.value)))
const coordinateError = computed(() => {
  const lat = coordinateText(latitude.value), lng = coordinateText(longitude.value)
  if (!lat && !lng) return ''
  if (!lat || !lng) return '经纬度须同时填写或同时留空'
  if (Number(lat) < -90 || Number(lat) > 90) return '纬度须在 -90 到 90 之间'
  if (Number(lng) < -180 || Number(lng) > 180) return '经度须在 -180 到 180 之间'
  return ''
})
const session = useAssessmentSession()
const { assessment, job, busy, working, waiting, notice, error } = session

function metadata(): RecordMetadata {
  const values: RecordMetadata = {
    address: address.value.trim() || undefined,
    district: district.value.trim() || undefined,
    facility: facility.value.trim() || undefined,
    scene: scene.value.trim() || undefined,
    data_source: dataSource.value,
    event_time: eventTime.value ? new Date(eventTime.value).toISOString() : undefined,
  }
  if (hasCoordinates.value) {
    values.latitude = Number(latitude.value)
    values.longitude = Number(longitude.value)
    values.coordinate_system = coordinateSystem.value
  }
  return values
}

async function submit() {
  if (!description.value.trim() || coordinateError.value) return
  const files = fileList.value
    .map((item) => (item.raw ? item.raw : (item as unknown as File)))
    .filter((item) => item instanceof File)
  await session.run((signal) => store.create(description.value.trim(), files, {
    wait: false, signal, entryMode: mode.value, metadata: metadata(),
  }))
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
  address.value = ''; district.value = ''; facility.value = ''; scene.value = ''
  latitude.value = ''; longitude.value = ''; coordinateSystem.value = 'wgs84'
  dataSource.value = 'report'; eventTime.value = ''
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

.intake-meta {
  padding: var(--s-3);
  border: 1px solid var(--border);
  border-radius: var(--r-control);
}

.intake-meta summary {
  cursor: pointer;
  font-weight: 600;
  color: var(--text-strong);
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 180px), 1fr));
  gap: var(--s-3);
  margin-top: var(--s-3);
}

.meta-grid input:not([type=checkbox]),
.meta-grid select {
  box-sizing: border-box;
  width: 100%;
  min-height: 36px;
  font: inherit;
  color: var(--text);
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--r-control);
  padding: 6px 8px;
}

.meta-error {
  color: var(--danger, #d14343);
}

@media (max-width: 860px) {
  .intake-row {
    grid-template-columns: 1fr;
  }
}
</style>
