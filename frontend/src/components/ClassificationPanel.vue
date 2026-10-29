<template>
  <section class="classification-panel" aria-labelledby="classification-title">
    <header class="classification-header">
      <h3 id="classification-title">{{ assessment.confirmed ? '已审核的分类记录' : '分类与人工录入' }}</h3>
      <el-tag>{{ assessment.risk_level ? `${assessment.risk_level} 级（人工）` : '未分级' }}</el-tag>
    </header>
    <p v-if="data?.is_demo" class="notice">Mock 演示：当前建议未分析图片内容。</p>
    <div class="classification-columns">
      <section aria-labelledby="suggestion-title">
        <h4 id="suggestion-title">AI 建议</h4>
        <p class="suggested-category">{{ statusText }}</p>
        <p>建议标签：{{ data?.suggested_tags.join('、') || '无' }}</p>
        <p v-if="assessment.scene_summary">{{ assessment.scene_summary }}</p>
        <p class="hint">分类体系 {{ data?.taxonomy_version || '加载中' }}。建议需结合现场核实。</p>
        <ul v-if="data?.warnings.length" class="warnings">
          <li v-for="warning in data.warnings" :key="warning">{{ warning }}</li>
        </ul>
        <div class="scene-images">
          <img v-for="image in assessment.images.filter(item => item.image_kind === 'original' && item.url)"
            :key="image.id" :src="image.url" :alt="`现场照片：${image.filename}`" loading="lazy" />
        </div>
      </section>
      <section aria-labelledby="entry-title">
        <h4 id="entry-title">人工分类</h4>
        <template v-if="assessment.confirmed">
          <p>{{ assessment.hazard_category }}</p>
          <p>标签：{{ data?.final_tags.join('、') || '无' }}</p>
          <p class="preserve-text">{{ assessment.conclusion || '未填写备注' }}</p>
        </template>
        <form v-else-if="editable" class="classification-form" @submit.prevent="save">
          <p v-if="loadError" role="alert">{{ loadError }} <el-button link @click="loadTaxonomy">重试加载分类选项</el-button></p>
          <fieldset :disabled="busy || loading || !taxonomy || taxonomy.version !== data?.taxonomy_version">
            <legend class="hint">保存录入后，交由复核员或管理员审核。</legend>
            <el-button v-if="data?.suggested_category" type="primary" plain @click="adopt">采用建议填写</el-button>
            <label :for="`classification-category-${assessment.id}`">最终类别</label>
            <select :id="`classification-category-${assessment.id}`" v-model="category" required>
              <option disabled value="">请选择已现场核实的类别</option>
              <option v-for="item in taxonomy?.categories" :key="item" :value="item">{{ item }}</option>
            </select>
            <fieldset class="tag-choices">
              <legend>最终标签（可多选）</legend>
              <label v-for="tag in taxonomy?.tags" :key="tag">
                <input v-model="tags" type="checkbox" :value="tag" />{{ tag }}
              </label>
            </fieldset>
            <label :for="`classification-level-${assessment.id}`">风险等级（人工选填）</label>
            <select :id="`classification-level-${assessment.id}`" v-model="level">
              <option :value="null">未分级</option>
              <option :value="1">一级 · 高风险</option>
              <option :value="2">二级 · 中风险</option>
              <option :value="3">三级 · 较低风险</option>
            </select>
            <label :for="`classification-note-${assessment.id}`">现场核实备注（可选）</label>
            <textarea :id="`classification-note-${assessment.id}`" v-model="note" :maxlength="2000" rows="3" />
            <el-button native-type="submit" type="primary" :loading="busy" :disabled="!category">保存人工录入</el-button>
          </fieldset>
          <p v-if="taxonomy && taxonomy.version !== data?.taxonomy_version" role="alert">分类体系版本不匹配，请重新查询记录。</p>
          <p v-if="error" class="save-error" role="alert">{{ error }}</p>
          <p v-if="saved" role="status">人工录入已保存，待审核。</p>
        </form>
        <p v-else class="hint">请等待任务结束后填写人工分类。</p>
      </section>
    </div>
    <section class="reference-section">
      <h4>检索到的参考条款</h4>
      <p class="hint">检索结果来自当前资料库；人工改分类后，仍须重新核对条款适用性。</p>
      <LegalEvidence :assessment="assessment" />
    </section>
    <p v-if="dirty && assessment.hazard_category" class="hint">有未保存的修改，请先保存人工录入再审核。</p>
    <HumanReviewPanel :assessment="assessment" :loading="loading || busy || dirty" @updated="emit('updated', $event)" />
    <el-button @click="emit('download')">导出分类记录</el-button>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api/client'
import { useAssessmentStore } from '../stores/assessment'
import type { Assessment, ClassificationTaxonomy } from '../types'
import { extractError } from '../utils/errors'
import HumanReviewPanel from './HumanReviewPanel.vue'
import LegalEvidence from './LegalEvidence.vue'

const props = defineProps<{ assessment: Assessment; loading?: boolean }>()
const emit = defineEmits<{ updated: [assessment: Assessment]; download: [] }>()
const store = useAssessmentStore()
const data = computed(() => props.assessment.classification)
const busy = computed(() => Boolean(store.reviewPending[props.assessment.id]))
const editable = computed(() => !props.assessment.confirmed
  && ['awaiting_human_review', 'needs_review'].includes(props.assessment.status))
const statusText = computed(() => {
  if (data.value?.suggestion_status === 'manual') return '仅人工录入，未请求 AI 分类'
  if (data.value?.suggestion_status === 'failed') return 'AI 分类失败，可继续人工录入'
  if (data.value?.suggestion_status === 'unknown') return '未知类别，请人工核实'
  return data.value?.suggested_category || '分类任务进行中'
})
const taxonomy = ref<ClassificationTaxonomy>()
const category = ref('')
const tags = ref<string[]>([])
const level = ref<number | null>(null)
const note = ref('')
const error = ref('')
const loadError = ref('')
const saved = ref(false)
const dirty = computed(() => category.value !== (props.assessment.hazard_category || '')
  || JSON.stringify([...tags.value].sort()) !== JSON.stringify([...(data.value?.final_tags || [])].sort())
  || level.value !== (props.assessment.risk_level ?? null) || note.value.trim() !== (props.assessment.conclusion || ''))
const controller = new AbortController()
onUnmounted(() => controller.abort())
onMounted(loadTaxonomy)
watch(() => [props.assessment.id, data.value?.revision], () => {
  category.value = props.assessment.hazard_category || ''
  tags.value = [...(data.value?.final_tags || [])]
  level.value = props.assessment.risk_level ?? null
  note.value = props.assessment.conclusion || ''
  error.value = ''
}, { immediate: true })

async function loadTaxonomy() {
  loadError.value = ''
  try {
    const result = await api.get<ClassificationTaxonomy>('/classification/taxonomy', { signal: controller.signal })
    taxonomy.value = result.data
  } catch (err) {
    if (!controller.signal.aborted) loadError.value = extractError(err)
  }
}

function adopt() {
  if (!data.value?.suggested_category) return
  category.value = data.value.suggested_category
  tags.value = [...data.value.suggested_tags]
  saved.value = false
}

async function save() {
  if (!editable.value || busy.value || props.loading || !category.value || !data.value || !taxonomy.value
    || taxonomy.value.version !== data.value.taxonomy_version) return
  const id = props.assessment.id
  error.value = ''
  saved.value = false
  try {
    const result = await store.saveClassification(id, {
      category: category.value, tags: [...tags.value], risk_level: level.value, note: note.value.trim(),
      taxonomy_version: data.value.taxonomy_version, revision: data.value.revision,
    })
    if (props.assessment.id !== id) return
    emit('updated', result)
    saved.value = true
  } catch (err) {
    if (props.assessment.id === id) error.value = extractError(err)
  }
}
</script>

<style scoped>
.classification-panel { overflow-wrap: anywhere; }
.classification-header { display: flex; align-items: baseline; justify-content: space-between; gap: var(--s-3); }
h3, h4 { margin: 0 0 var(--s-3); color: var(--text-strong); }
.classification-columns { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--s-5); }
.classification-columns > section { min-width: 0; }
.classification-form fieldset { border: 0; padding: 0; margin: 0; min-width: 0; }
.classification-form label { display: block; margin-top: var(--s-3); margin-bottom: var(--s-1); }
.classification-form select, .classification-form textarea { box-sizing: border-box; width: 100%; min-height: 40px;
  padding: 8px; border: 1px solid var(--border); border-radius: var(--r-control); background: var(--panel);
  color: var(--text); font: inherit; }
.classification-form select:focus-visible, .classification-form textarea:focus-visible,
.tag-choices input:focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }
.classification-form fieldset:disabled { opacity: .65; }
.classification-form button { margin-top: var(--s-3); }
.classification-form .tag-choices { display: flex; flex-wrap: wrap; gap: var(--s-2) var(--s-3); margin-top: var(--s-3); }
.tag-choices label { display: inline-flex; gap: 6px; align-items: center; margin: 0; }
.hint, .warnings { color: var(--muted); font-size: var(--fs-sm); }
.warnings { padding-left: 20px; }
.notice { color: var(--warning); }
.save-error { color: var(--danger); }
.reference-section { margin-top: var(--s-5); padding-top: var(--s-4); border-top: 1px solid var(--border); }
.scene-images { display: flex; flex-wrap: wrap; gap: var(--s-2); }
.scene-images img { width: 140px; max-width: 100%; height: 120px; object-fit: contain; background: var(--panel); }
.preserve-text { white-space: pre-wrap; }
@media (max-width: 760px) {
  .classification-columns { grid-template-columns: 1fr; }
  .classification-form select, .classification-form textarea { font-size: 16px; }
}
</style>
