<template>
  <section class="page">
    <h1 class="page-title">历史研判记录</h1>
    <p class="page-subtitle">查看此前上传的隐患研判与整改工单</p>

    <el-card v-loading="store.loading">
      <div class="toolbar">
        <el-select v-model="statusFilter" placeholder="按状态筛选" clearable style="width: 200px">
          <el-option label="自动完成" value="completed" />
          <el-option label="研判进行中" value="pending" />
          <el-option label="任务失败" value="failed" />
          <el-option label="需要重新研判" value="needs_review" />
          <el-option label="需要补充信息" value="needs_more_info" />
          <el-option label="需要人工复核" value="awaiting_human_review" />
          <el-option label="已确认" value="confirmed" />
          <el-option label="已导入" value="imported" />
        </el-select>
        <el-button type="primary" plain @click="load">
          <el-icon><Search /></el-icon>
          刷新
        </el-button>
      </div>

      <el-table :data="items" v-loading="store.loading">
        <template #empty>
          <div class="empty-state">
            <p class="empty-title">还没有研判记录</p>
            <p class="empty-hint">到「现场研判」上传现场照片和情况描述，记录会自动出现在这里。</p>
            <el-button type="primary" plain @click="router.push('/')">去现场研判</el-button>
          </div>
        </template>
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="220" show-overflow-tooltip />
        <el-table-column label="人工类别 / 历史类别" min-width="170">
          <template #default="{ row }">{{ row.record_mode === 'imported' ? '—' : row.hazard_category || '待人工录入' }}</template>
        </el-table-column>
        <el-table-column label="人工标签" min-width="150">
          <template #default="{ row }">{{ row.classification?.final_tags.join('、') || '—' }}</template>
        </el-table-column>
        <el-table-column label="等级" width="90" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.risk_level" :type="levelType(row.risk_level)">{{ levelLabel(row.risk_level) }}</el-tag>
            <span v-else>未分级</span>
          </template>
        </el-table-column>
        <el-table-column label="置信度" width="100" align="center">
          <template #default="{ row }">{{ formatPercent(row.confidence) }}</template>
        </el-table-column>
        <el-table-column label="风险分" width="90" align="center">
          <template #default="{ row }">
            <span v-if="row.risk_score !== undefined && row.risk_score !== null">{{ row.risk_score }}</span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click="open(row.id)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card v-if="auth.canManageKnowledge" class="import-card">
      <details>
        <summary>批量导入案例（JSON）</summary>
        <p class="import-hint">
          每行须包含 source_ref、description、data_source（report/public_case/simulated）；可选 address、district、
          facility、scene、latitude、longitude、coordinate_system、event_time。相同来源下重复的外部编号会跳过。
        </p>
        <div class="import-actions">
          <input type="file" accept=".json,application/json" aria-label="导入 JSON 文件" @change="onImportFile" />
          <el-button type="primary" plain :disabled="!importRows.length" :loading="importing" @click="runImport">
            导入{{ importRows.length ? ` ${importRows.length} 条` : '' }}
          </el-button>
          <span v-if="importFileName" class="import-hint">{{ importFileName }}</span>
        </div>
        <div v-if="importResult" class="import-result" role="status">
          <p>
            批次 {{ importResult.batch_id }}：成功 {{ importResult.imported }} 条，
            重复 {{ importResult.duplicates.length }} 条，失败 {{ importResult.failures.length }} 条。
          </p>
          <p v-if="importResult.duplicates.length">重复行：第 {{ importResult.duplicates.join('、') }} 行</p>
          <ul v-if="importResult.failures.length">
            <li v-for="failure in importResult.failures" :key="failure.row">
              第 {{ failure.row }} 行{{ failure.source_ref ? `（${failure.source_ref}）` : '' }}：{{ failure.reason }}
            </li>
          </ul>
        </div>
        <p v-if="importError" class="import-error" role="alert">{{ importError }}</p>
      </details>
    </el-card>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ElMessage } from 'element-plus'

import { useAssessmentStore } from '../stores/assessment'
import { useAuthStore } from '../stores/auth'
import { extractError } from '../utils/errors'
import type { Assessment, ImportResult } from '../types'

const router = useRouter()
const store = useAssessmentStore()
const auth = useAuthStore()
const items = ref<Assessment[]>([])
const statusFilter = ref('')
const importRows = ref<unknown[]>([])
const importFileName = ref('')
const importResult = ref<ImportResult | null>(null)
const importError = ref('')
const importing = ref(false)

onMounted(load)

async function load() {
  try {
    items.value = await store.list(statusFilter.value || undefined)
  } catch (err) {
    ElMessage.error(extractError(err))
  }
}

async function onImportFile(event: Event) {
  importError.value = ''
  importResult.value = null
  importRows.value = []
  importFileName.value = ''
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  try {
    const parsed: unknown = JSON.parse(await file.text())
    if (!Array.isArray(parsed) || !parsed.length) throw new Error('JSON 须为非空数组')
    importRows.value = parsed
    importFileName.value = `${file.name}（${parsed.length} 条）`
  } catch (err) {
    importError.value = err instanceof Error ? err.message : 'JSON 解析失败'
  }
}

async function runImport() {
  if (!importRows.value.length || importing.value) return
  importing.value = true
  importError.value = ''
  try {
    importResult.value = await store.importAssessments(importRows.value)
    await load()
  } catch (err) {
    importError.value = extractError(err)
  } finally {
    importing.value = false
  }
}

function open(id: string) {
  router.push(`/assessments/${id}`)
}

function formatTime(value: string) {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function formatPercent(value?: number) {
  return value === undefined || value === null ? '-' : `${Math.round(value * 100)}%`
}

function levelType(level: number) {
  return level === 1 ? 'danger' : level === 2 ? 'warning' : 'success'
}

function levelLabel(level: number) {
  if (level === 1) return '高风险'
  if (level === 2) return '中风险'
  return '较低风险'
}

function statusType(status: string) {
  if (status === 'completed') return 'success'
  if (status === 'confirmed') return 'primary'
  if (status === 'awaiting_human_review') return 'warning'
  if (status === 'needs_review') return 'warning'
  if (status === 'needs_more_info') return 'info'
  return 'info'
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    completed: '自动完成',
    confirmed: '已确认',
    needs_review: '待重新复核',
    awaiting_human_review: '需要人工复核',
    needs_more_info: '需要补充信息',
    processing: '处理中',
    pending: '研判进行中',
    failed: '任务失败',
    imported: '已导入',
  }
  return labels[status] || status
}
</script>

<style scoped>
.toolbar {
  display: flex;
  gap: var(--s-3);
  margin-bottom: var(--s-4);
}

.empty-state {
  padding: var(--s-5) var(--s-4);
}

.empty-title {
  margin: 0 0 var(--s-1);
  color: var(--text-strong);
  font-weight: 600;
}

.empty-hint {
  margin: 0 0 var(--s-4);
  color: var(--muted);
  font-size: var(--fs-sm);
}

.import-card {
  margin-top: var(--s-4);
}

.import-card summary {
  cursor: pointer;
  font-weight: 600;
  color: var(--text-strong);
}

.import-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s-3);
  margin-top: var(--s-3);
}

.import-hint {
  margin: var(--s-2) 0 0;
  color: var(--muted);
  font-size: var(--fs-sm);
  overflow-wrap: anywhere;
}

.import-result {
  margin-top: var(--s-3);
  padding: var(--s-3);
  border: 1px solid var(--border);
  border-radius: var(--r-control);
}

.import-result p { margin: 0 0 var(--s-2); }
.import-result ul { margin: 0; padding-left: 24px; }
.import-error { color: var(--danger, #d14343); }
</style>
