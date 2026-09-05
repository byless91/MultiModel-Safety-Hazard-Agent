<template>
  <section class="page">
    <h1 class="page-title">知识库管理</h1>
    <p class="page-subtitle">上传法规文档、查看内容、触发切片与向量重建</p>

    <el-card v-loading="store.loading">
      <template #header>上传知识文档</template>
      <el-form label-position="top" class="doc-form">
        <div class="doc-grid">
          <el-form-item label="文档标题">
            <el-input v-model="title" placeholder="如：消防法第二十八条" />
          </el-form-item>
          <el-form-item label="来源">
            <el-input v-model="source" placeholder="如：国家法律法规数据库或官网链接" />
          </el-form-item>
        </div>
        <el-form-item label="文件（.txt 或 .md，支持 YAML 元数据头）">
          <el-upload
            :auto-upload="false"
            :limit="1"
            accept=".txt,.md"
            :on-change="onFileChange"
          >
            <el-button type="primary" plain>
              <el-icon><Upload /></el-icon>
              选择文件
            </el-button>
          </el-upload>
        </el-form-item>
        <div class="doc-actions">
          <el-button type="primary" :loading="store.loading" :disabled="!selectedFile" @click="upload">
            <el-icon><UploadFilled /></el-icon>
            上传文档
          </el-button>
          <el-button type="warning" :loading="store.loading" @click="rebuild">
            <el-icon><Refresh /></el-icon>
            重新构建知识库
          </el-button>
        </div>
        <p v-if="rebuildResult" class="rebuild-tip">
          重建完成：{{ rebuildResult.records }} 条切片 / {{ rebuildResult.chunks }} 条向量索引
        </p>
      </el-form>
    </el-card>

    <el-card v-loading="store.loading" class="list-card">
      <template #header>文档列表</template>
      <el-table :data="documents" empty-text="暂无文档">
        <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
        <el-table-column prop="source" label="来源" min-width="220" show-overflow-tooltip />
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag type="success">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click="openPreview(row.id)">查看</el-button>
            <el-button link type="danger" @click="remove(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="previewOpen" title="文档内容预览" width="720px">
      <pre class="preview-text">{{ preview?.content }}</pre>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { ElMessage, type UploadFile } from 'element-plus'
import { onMounted, ref } from 'vue'

import { useAssessmentStore } from '../stores/assessment'
import type { KnowledgeDocument, KnowledgeDocumentDetail } from '../types'

const store = useAssessmentStore()
const documents = ref<KnowledgeDocument[]>([])
const title = ref('')
const source = ref('')
const selectedFile = ref<File | null>(null)
const previewOpen = ref(false)
const preview = ref<KnowledgeDocumentDetail | null>(null)
const rebuildResult = ref<{
  records: number
  chunks: number
  embedding_fallback: boolean
} | null>(null)

onMounted(load)

async function load() {
  documents.value = await store.listDocuments()
}

function onFileChange(file: UploadFile) {
  selectedFile.value = file.raw ?? null
}

async function upload() {
  if (!selectedFile.value) return
  await store.uploadDocument(
    selectedFile.value,
    title.value || selectedFile.value.name,
    source.value,
  )
  ElMessage.success('文档已上传，可点击重新构建知识库生效')
  title.value = ''
  source.value = ''
  selectedFile.value = null
  await load()
}

async function rebuild() {
  rebuildResult.value = await store.rebuildKnowledge()
  ElMessage.success('知识库已重建')
}

async function openPreview(id: string) {
  preview.value = await store.getDocument(id)
  previewOpen.value = true
}

async function remove(id: string) {
  await store.deleteDocument(id)
  ElMessage.success('文档已删除，请重新构建知识库生效')
  await load()
}

function formatTime(value: string) {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.doc-form {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.doc-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}

.doc-actions {
  display: flex;
  gap: 12px;
  margin-top: 4px;
}

.list-card {
  margin-top: 16px;
}

.rebuild-tip {
  color: #64748b;
  margin: 10px 0 0;
}

.preview-text {
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 13px;
  line-height: 1.6;
  max-height: 60vh;
  overflow: auto;
}
</style>
