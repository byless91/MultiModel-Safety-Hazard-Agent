<template>
  <section class="page">
    <h1 class="page-title">历史研判记录</h1>
    <p class="page-subtitle">查看此前上传的隐患研判与整改工单</p>

    <el-card v-loading="store.loading">
      <div class="toolbar">
        <el-select v-model="statusFilter" placeholder="按状态筛选" clearable style="width: 200px">
          <el-option label="自动完成" value="completed" />
          <el-option label="需要重新研判" value="needs_review" />
          <el-option label="需要补充信息" value="needs_more_info" />
          <el-option label="需要人工复核" value="awaiting_human_review" />
          <el-option label="已确认" value="confirmed" />
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
        <el-table-column prop="hazard_category" label="隐患类别" min-width="150" />
        <el-table-column label="等级" width="90" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.risk_level" :type="levelType(row.risk_level)">{{ levelLabel(row.risk_level) }}</el-tag>
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
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { useAssessmentStore } from '../stores/assessment'
import type { Assessment } from '../types'

const router = useRouter()
const store = useAssessmentStore()
const items = ref<Assessment[]>([])
const statusFilter = ref('')

onMounted(load)

async function load() {
  items.value = await store.list(statusFilter.value || undefined)
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
    needs_review: '需要重新研判',
    awaiting_human_review: '需要人工复核',
    needs_more_info: '需要补充信息',
    processing: '处理中',
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
</style>
