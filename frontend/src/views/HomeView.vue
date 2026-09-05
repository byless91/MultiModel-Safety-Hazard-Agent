<template>
  <section class="page">
    <h1 class="page-title">现场隐患智能研判</h1>
    <p class="page-subtitle">上传现场照片并填写描述，系统自动完成识别、检索、分级与成文</p>

    <el-card v-loading="store.loading">
      <form class="input-form" @submit.prevent="submit">
        <div class="form-row">
          <label class="form-label">现场照片（最多 3 张）</label>
          <el-upload
            v-model:file-list="fileList"
            list-type="picture-card"
            accept="image/*"
            multiple
            :auto-upload="false"
            :limit="3"
            :on-exceed="onExceed"
          >
            <el-icon><Plus /></el-icon>
          </el-upload>
        </div>

        <div class="form-row">
          <label class="form-label">隐患描述</label>
          <el-input
            v-model="description"
            type="textarea"
            :rows="5"
            placeholder="例如：××小区 3 栋 2 单元楼道堆放纸箱杂物，通行明显受阻"
          />
        </div>

        <div class="form-actions">
          <el-button type="primary" native-type="submit" :loading="store.loading" :disabled="!description.trim()">
            <el-icon><UploadFilled /></el-icon>
            开始研判
          </el-button>
          <el-button :disabled="store.loading" @click="resetForm">重置</el-button>
        </div>
      </form>
    </el-card>

    <el-alert
      v-if="store.error"
      class="error-alert"
      :title="store.error"
      type="error"
      :closable="false"
      show-icon
    />

    <el-card v-if="assessment" class="result-panel">
      <template #header>
        <div class="result-panel-head">
          <span>研判结果</span>
          <span class="result-id">{{ assessment.id.slice(0, 8) }}</span>
        </div>
      </template>
      <AssessmentResult
        :assessment="assessment"
        :loading="store.loading"
        @followup="onFollowup"
        @confirm="onConfirm"
        @updated="onUpdated"
      />
    </el-card>
  </section>
</template>

<script setup lang="ts">
import { ElMessage, type UploadFile, type UploadFiles } from 'element-plus'
import { ref } from 'vue'

import AssessmentResult from '../components/AssessmentResult.vue'
import { useAssessmentStore } from '../stores/assessment'
import type { Assessment } from '../types'

const store = useAssessmentStore()
const description = ref('')
const fileList = ref<UploadFile[]>([])
const assessment = ref<Assessment | null>(null)

async function submit() {
  if (!description.value.trim()) return
  const files = fileList.value
    .map((item) => (item.raw ? item.raw : (item as unknown as File)))
    .filter((item) => item instanceof File)
  assessment.value = await store.create(description.value.trim(), files)
  ElMessage.success('研判完成')
}

async function onFollowup(answer: string) {
  if (!assessment.value) return
  assessment.value = await store.followup(assessment.value.id, answer)
}

async function onConfirm() {
  if (!assessment.value) return
  assessment.value = await store.confirm(assessment.value.id, true, {})
  ElMessage.success('结果已确认')
}

function onUpdated(updated: Assessment) {
  assessment.value = updated
}

function resetForm() {
  description.value = ''
  fileList.value = []
  assessment.value = null
  store.error = ''
}

function onExceed(files: UploadFiles) {
  ElMessage.warning(`最多上传 3 张图片`)
}
</script>

<style scoped>
.input-form {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.form-row {
  min-width: 0;
}

.form-label {
  display: block;
  margin-bottom: 8px;
  font-weight: 600;
  color: #334155;
}

.form-actions {
  display: flex;
  gap: 10px;
}

.error-alert {
  margin-top: 14px;
}

.result-panel {
  margin-top: 18px;
}

.result-panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.result-id {
  color: #94a3b8;
  font-size: 12px;
  word-break: break-all;
}
</style>
