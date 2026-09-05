<template>
  <section class="page">
    <el-button text class="back-button" @click="$router.back()">
      <el-icon><ArrowLeft /></el-icon>
      返回
    </el-button>
    <h1 class="page-title">研判详情</h1>
    <p class="page-subtitle">{{ assessment?.description || '加载中' }}</p>

    <el-card v-if="assessment" v-loading="store.loading">
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
import { ElMessage } from 'element-plus'
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import AssessmentResult from '../components/AssessmentResult.vue'
import { useAssessmentStore } from '../stores/assessment'
import type { Assessment } from '../types'

const route = useRoute()
const store = useAssessmentStore()
const assessment = ref<Assessment | null>(null)

onMounted(load)

async function load() {
  const id = String(route.params.id)
  assessment.value = await store.get(id)
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
  margin: 0 0 8px -12px;
}
</style>
