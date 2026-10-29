<template>
  <section class="page">
    <el-button text class="back-button" @click="$router.back()"><el-icon><ArrowLeft /></el-icon>返回</el-button>
    <h1 class="page-title">{{ assessment?.record_mode === 'classification' ? '分类记录详情' : '研判详情' }}</h1>
    <p class="page-subtitle">{{ assessment?.description || '正在查询研判记录' }}</p>
    <el-skeleton v-if="!assessment && busy" :rows="6" animated />
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-button v-if="error && !assessment" :disabled="busy" @click="load">重新查询记录</el-button>
    <JobProgress :assessment="assessment" :job="job" :busy="busy" :waiting="waiting" :notice="notice"
      :working="working" @resume="session.resume" />
    <section v-if="assessment" class="detail-panel">
      <p v-if="working && assessment.report" class="previous-result">任务执行中，以下为此前保留的研判结果。</p>
      <p v-if="job?.status === 'failed' && assessment.report" class="previous-result">本次任务失败，以下为此前保留的研判结果。</p>
      <AssessmentResult :assessment="assessment" :loading="busy || working"
        @followup="onFollowup" @updated="session.update" />
    </section>
  </section>
</template>

<script setup lang="ts">
import { watch } from 'vue'
import { useRoute } from 'vue-router'
import AssessmentResult from '../components/AssessmentResult.vue'
import JobProgress from '../components/JobProgress.vue'
import { useAssessmentSession } from '../composables/useAssessmentSession'
import { useAssessmentStore } from '../stores/assessment'

const route = useRoute()
const store = useAssessmentStore()
const session = useAssessmentSession()
const { assessment, job, busy, working, waiting, error, notice } = session
watch(() => String(route.params.id), () => { void load() }, { immediate: true })
async function load() { await session.open(String(route.params.id)) }
async function onFollowup(answer: string) {
  if (!assessment.value) return
  const id = assessment.value.id
  await session.run((signal) => store.followup(id, answer, { wait: false, signal }))
}
</script>

<style scoped>
.back-button { margin: 0 0 var(--s-2) -12px; }
.detail-panel { padding: var(--s-4); background: var(--panel); border: 1px solid var(--border); border-radius: var(--r-card); }
.previous-result { color: var(--muted); }
</style>
