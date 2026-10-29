<template>
  <section class="human-review" aria-labelledby="review-title">
    <h4 id="review-title">人工复核</h4>
    <p v-if="assessment.confirmed" class="review-status">已人工定稿。需要重新研判时，请新建关联记录。</p>
    <p v-else-if="resolution && !resolution.confirmed" class="review-status">当前结论已拒绝，等待重新复核。</p>
    <ul v-if="assessment.review_reasons?.length" class="review-reasons">
      <li v-for="reason in assessment.review_reasons" :key="reason">{{ reason }}</li>
    </ul>

    <form v-if="canAct" class="review-form" @submit.prevent="save">
      <fieldset :disabled="busy || loading">
        <legend>复核处理</legend>
        <el-radio-group v-model="action" aria-label="复核方式">
          <el-radio-button value="approve">批准定稿</el-radio-button>
          <el-radio-button value="reject">拒绝当前结论</el-radio-button>
          <el-radio-button value="edit">修订并定稿</el-radio-button>
        </el-radio-group>
        <div v-if="action === 'edit'" class="edit-fields">
          <div class="review-field">
            <label :for="`review-category-${assessment.id}`">隐患类别</label>
            <el-input :id="`review-category-${assessment.id}`" v-model="category" :maxlength="128" />
          </div>
          <div class="review-field">
            <label :for="`review-level-${assessment.id}`">风险等级</label>
            <el-select :id="`review-level-${assessment.id}`" v-model="level" aria-label="风险等级">
              <el-option :value="1" label="一级 · 立即处置" />
              <el-option :value="2" label="二级 · 限期整改" />
              <el-option :value="3" label="三级 · 建议改进" />
            </el-select>
          </div>
          <div class="review-field review-field--wide">
            <label :for="`review-conclusion-${assessment.id}`">人工结论</label>
            <el-input :id="`review-conclusion-${assessment.id}`" v-model="conclusion" type="textarea"
              :rows="3" :maxlength="2000" show-word-limit />
          </div>
        </div>
        <div class="review-field">
          <label :for="`review-note-${assessment.id}`">复核意见{{ action === 'reject' ? '（必填）' : '（可选）' }}</label>
          <el-input :id="`review-note-${assessment.id}`" v-model="note" type="textarea" :rows="3"
            :maxlength="2000" show-word-limit :aria-required="action === 'reject'" />
        </div>
        <p v-if="auth.authMode === 'none' || auth.authMode === 'token'" class="review-hint">
          当前模式未绑定个人用户身份，复核记录不具备实名用户信息。
        </p>
        <p v-if="error" class="review-error" role="alert">{{ error }}</p>
        <el-button native-type="submit" :type="action === 'reject' ? 'warning' : 'primary'"
          :loading="busy" :disabled="busy || loading">{{ actionLabel }}</el-button>
      </fieldset>
    </form>
    <p v-else-if="!assessment.confirmed && !auth.canReview" class="review-hint">当前账号可查看结果，请复核员或管理员处理。</p>
    <p v-else-if="!assessment.confirmed && !reviewable" class="review-hint">请等待研判结束后再复核。</p>

    <details v-if="original" class="original-result">
      <summary>AI 原始结论与规则结果</summary>
      <template v-if="original.available">
        <p>{{ snapshotText(original) }}</p>
        <p class="preserve-text">{{ original.conclusion || '原始结论未提供' }}</p>
        <p class="review-hint">模型分析页保留 AI / 规则原始计算；人工修订不会重新计算原始风险分数。</p>
      </template>
      <p v-else>{{ original.reason || '历史 AI 快照未保存，无法恢复。' }}</p>
    </details>

    <div v-if="history.length" class="review-history">
      <h5>复核记录</h5>
      <ol>
        <li v-for="(entry, index) in history" :key="entry.event_id || `${entry.resolved_at}-${index}`">
          <p><strong>{{ eventLabel(entry) }}</strong> · {{ entry.reviewer || '未绑定个人身份' }}
            <time v-if="entry.resolved_at"> · {{ formatTime(entry.resolved_at) }}</time></p>
          <p v-if="entry.note" class="preserve-text">意见：{{ entry.note }}</p>
          <template v-if="entry.before && entry.after">
            <p>修改前：{{ snapshotText(entry.before) }}；{{ entry.before.conclusion || '结论未提供' }}</p>
            <p>修改后：{{ snapshotText(entry.after) }}；{{ entry.after.conclusion || '结论未提供' }}</p>
          </template>
          <p v-else class="review-hint">历史记录未保存修改前后快照。</p>
        </li>
      </ol>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useAssessmentStore } from '../stores/assessment'
import { useAuthStore } from '../stores/auth'
import type { Assessment, HumanReviewResolution, ReviewEdits, ReviewEvent, ReviewSnapshot } from '../types'
import { extractError } from '../utils/errors'
import { formatTime } from '../utils/format'

const props = defineProps<{ assessment: Assessment; loading?: boolean }>()
const emit = defineEmits<{ updated: [assessment: Assessment] }>()
const store = useAssessmentStore()
const auth = useAuthStore()
const action = ref<'approve' | 'reject' | 'edit'>('approve')
const note = ref('')
const category = ref('')
const level = ref<number | undefined>()
const conclusion = ref('')
const error = ref('')
const busy = computed(() => Boolean(store.reviewPending[props.assessment.id]))
const resolution = computed(() => props.assessment.human_review?.resolution)
const original = computed(() => props.assessment.human_review?.ai_original)
const history = computed<ReviewEvent[]>(() => props.assessment.human_review?.history
  ?? (resolution.value ? [resolution.value] : []))
const reviewable = computed(() => ['completed', 'awaiting_human_review', 'needs_review'].includes(props.assessment.status))
const canAct = computed(() => auth.canReview && reviewable.value && !props.assessment.confirmed)
const actionLabel = computed(() => action.value === 'reject' ? '提交拒绝意见'
  : action.value === 'edit' ? '保存修订并定稿' : '批准并定稿')

function reset() {
  category.value = props.assessment.hazard_category || props.assessment.report?.category || ''
  level.value = props.assessment.risk_level ?? props.assessment.report?.level
  conclusion.value = props.assessment.conclusion || props.assessment.report?.summary || ''
  action.value = 'approve'
  note.value = ''
  error.value = ''
}
watch(() => props.assessment.id, reset, { immediate: true })

function snapshotText(snapshot: ReviewSnapshot) {
  return `类别：${snapshot.hazard_category || '未提供'}，等级：${snapshot.risk_level ?? '未提供'}`
}

function eventLabel(entry: HumanReviewResolution) {
  return !entry.confirmed ? '拒绝当前结论' : Object.keys(entry.edits || {}).length ? '修订并定稿' : '批准定稿'
}

async function save() {
  if (!canAct.value || busy.value || props.loading) return
  error.value = ''
  if (action.value === 'reject' && !note.value.trim()) {
    error.value = '拒绝当前结论时，请填写复核意见。'
    return
  }
  const edits: ReviewEdits = {}
  if (action.value === 'edit') {
    if (!category.value.trim() || !conclusion.value.trim() || ![1, 2, 3].includes(level.value ?? 0)) {
      error.value = '请填写隐患类别、有效风险等级和人工结论。'
      return
    }
    if (category.value.trim() !== props.assessment.hazard_category) edits.hazard_category = category.value.trim()
    if (level.value !== props.assessment.risk_level) edits.risk_level = level.value
    if (conclusion.value.trim() !== (props.assessment.conclusion || props.assessment.report?.summary)) {
      edits.conclusion = conclusion.value.trim()
    }
    if (!Object.keys(edits).length) {
      error.value = '请至少修改一项内容，或选择批准定稿。'
      return
    }
  }
  const id = props.assessment.id
  try {
    const updated = await store.confirm(id, { confirmed: action.value !== 'reject', edits, note: note.value.trim() })
    if (props.assessment.id !== id) return
    emit('updated', updated)
    note.value = ''
  } catch (err) {
    if (props.assessment.id === id) error.value = extractError(err)
  }
}
</script>

<style scoped>
.human-review { padding-block: var(--s-4); border-top: 1px solid var(--border); overflow-wrap: anywhere; }
h4, h5 { margin: 0 0 var(--s-3); color: var(--text-strong); }
h4 { font-size: var(--fs-md); }
h5 { font-size: var(--fs-sm); }
.review-form fieldset { border: 0; padding: 0; margin: var(--s-4) 0; min-width: 0; }
legend, .review-field label { margin-bottom: var(--s-2); font-weight: 600; }
.review-field { display: flex; flex-direction: column; gap: var(--s-1); margin-block: var(--s-3); min-width: 0; }
.edit-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 var(--s-4); }
.review-field--wide { grid-column: 1 / -1; }
.review-reasons { padding-left: 20px; color: var(--warning); }
.review-hint { color: var(--muted); font-size: var(--fs-sm); }
.review-error { color: var(--danger); }
.review-status { font-weight: 600; }
.preserve-text { white-space: pre-wrap; }
.original-result, .review-history { margin-top: var(--s-4); padding-top: var(--s-3); border-top: 1px solid var(--border); }
summary { cursor: pointer; color: var(--text-strong); }
.review-history ol { padding-left: 20px; }
.review-history li { padding-block: var(--s-2); }
.review-history p { margin-block: var(--s-1); }
@media (max-width: 600px) {
  .edit-fields { grid-template-columns: 1fr; }
  :deep(.el-radio-group) { display: flex; flex-wrap: wrap; gap: var(--s-2); }
  :deep(.el-radio-button__inner) { border-radius: var(--r-control); border: 1px solid var(--border); }
  :deep(.el-input__inner), :deep(.el-textarea__inner) { font-size: 16px; }
}
</style>
