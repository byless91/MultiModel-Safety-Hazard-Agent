<template>
  <section class="page">
    <el-button text class="back-button" @click="$router.back()">
      <el-icon><ArrowLeft /></el-icon>
      返回
    </el-button>
    <h1 class="page-title">研判详情</h1>
    <p class="page-subtitle">{{ assessment?.description || '正在加载研判记录' }}</p>

    <el-skeleton v-if="!assessment && store.loading" :rows="6" animated />

    <el-alert
      v-else-if="!assessment && loadError"
      title="没有找到这条研判记录，可能已被删除"
      type="warning"
      :closable="false"
      show-icon
    />

    <section v-else-if="assessment" class="detail-panel">
      <AssessmentResult
        :assessment="assessment"
        :loading="store.loading"
        @followup="onFollowup"
        @confirm="onConfirm"
        @updated="onUpdated"
      />
    </section>
  </section>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import AssessmentResult from '../components/AssessmentResult.vue'
import { useAssessmentStore } from '../stores/assessment'
import type { Assessment } from '../types'

const route = useRoute()
const store = useAssessmentStore()
const assessment = ref<Assessment | null>(null)
const loadError = ref(false)

onMounted(load)

async function load() {
  loadError.value = false
  try {
    const id = String(route.params.id)
    assessment.value = await store.get(id)
  } catch {
    loadError.value = true
  }
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
</script>

<style scoped>
.back-button {
  margin: 0 0 var(--s-2) -12px;
}

.detail-panel {
  padding: var(--s-4);
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--r-card);
}
</style>
