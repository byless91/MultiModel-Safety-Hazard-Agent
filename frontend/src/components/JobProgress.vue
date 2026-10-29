<template>
  <section v-if="assessment && (job || waiting || pending || assessment.status === 'failed')" class="job-progress"
    role="status" aria-live="polite">
    <h2>{{ title }}</h2>
    <p v-if="job && working && !waiting">{{ assessment.record_mode === 'classification' && job.progress_step === 'analyze'
      ? '正在生成类别与标签建议' : steps[job.progress_step] || '正在处理任务' }}</p>
    <p v-else-if="job?.status === 'succeeded' && assessment">当前状态：{{ statuses[assessment.status] || '记录已更新' }}</p>
    <p v-if="notice">{{ notice }}</p>
    <p v-if="job?.status === 'failed'">{{ job.error || '任务执行失败，原记录已保留。' }}</p>
    <div class="job-links">
      <el-button v-if="waiting" :disabled="busy" @click="$emit('resume')">继续查询</el-button>
      <RouterLink v-if="assessment" :to="`/assessments/${assessment.id}`">查看研判记录</RouterLink>
      <RouterLink to="/history">历史记录</RouterLink>
    </div>
    <p v-if="working" class="job-hint">可离开此页；任务继续执行，重新进入记录后会恢复查询。</p>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Assessment, JobOut } from '../types'

const props = defineProps<{ assessment: Assessment | null; job: JobOut | null; waiting: boolean;
  busy: boolean; notice: string; working: boolean }>()
defineEmits<{ resume: [] }>()
const pending = computed(() => props.assessment && ['pending', 'processing'].includes(props.assessment.status))
const title = computed(() => props.job?.status === 'failed' || props.assessment?.status === 'failed'
  ? '研判任务失败' : props.waiting ? '已暂停本地等待' : props.job?.status === 'queued' ? '研判正在排队'
    : props.job?.status === 'running' || pending.value ? '研判进行中'
      : props.assessment?.status === 'needs_more_info' ? '需要补充现场信息' : '研判任务已结束')
const steps: Record<string, string> = { queued: '等待执行', analyze: '多模型分析中', retrieve: '法规检索中',
  refine: '证据二次研判中', judge: '融合研判中', evidence: '证据校验中', generate: '生成报告中',
  needs_more_info: '等待补充信息', done: '处理已结束', completed: '处理已结束' }
const statuses: Record<string, string> = { pending: '研判进行中', processing: '研判进行中',
  needs_more_info: '需要补充现场信息', completed: '自动研判完成', awaiting_human_review: '待人工复核',
  needs_review: '待重新复核', confirmed: '已人工定稿', failed: '任务失败' }
</script>

<style scoped>
.job-progress { margin-block: var(--s-4); padding: var(--s-4); border: 1px solid var(--border);
  border-radius: var(--r-card); background: var(--panel); overflow-wrap: anywhere; }
h2 { font-size: var(--fs-md); margin: 0 0 var(--s-2); }
.job-links { display: flex; align-items: center; flex-wrap: wrap; gap: var(--s-3); }
.job-links a { color: var(--brand); text-underline-offset: 3px; }
.job-hint { color: var(--muted); font-size: var(--fs-sm); }
</style>
