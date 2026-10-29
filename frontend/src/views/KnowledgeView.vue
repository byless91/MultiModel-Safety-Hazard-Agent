<template>
  <section class="page knowledge-page">
    <h1 class="page-title">知识库管理</h1>
    <p class="page-subtitle">按行业查询已审核条款；每个版本独立保留来源、适用范围和审核记录。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-button v-if="error" @click="initialize">重新加载目录与列表</el-button>
    <el-card class="list-card">
      <form class="toolbar" @submit.prevent="search">
        <label>行业目录
          <select v-model="industryFilter" aria-label="行业目录" @change="filtersChanged">
            <option value="">全部行业</option>
            <option v-for="item in industries" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </label>
        <label>审核状态
          <select v-model="statusFilter" aria-label="审核状态" @change="load">
            <option value="">全部状态</option>
            <option v-for="(label, key) in statuses" :key="key" :value="key">{{ label }}</option>
          </select>
        </label>
        <label class="search-input">条款关键词
          <input v-model="query" aria-label="条款关键词" :maxlength="2000" placeholder="如：疏散通道" />
        </label>
        <el-button native-type="submit" type="primary" :disabled="!query.trim()" :loading="searching">检索已审核条款</el-button>
      </form>
      <section v-if="searchResult" class="search-results" aria-live="polite">
        <p>{{ searchResult.notice }}</p>
        <ol v-if="searchResult.items.length">
          <li v-for="item in searchResult.items" :key="item.id">
            <strong>{{ item.document }} {{ item.article }} · {{ item.version }}</strong>
            <p>{{ item.text }}</p><p class="hint">适用范围：{{ item.applicability }}</p>
            <el-button v-if="item.document_id" link type="primary" @click="openPreview(item.document_id)">查看引用版本</el-button>
          </li>
        </ol>
      </section>
      <h2>文档版本</h2>
      <el-table v-loading="listing" :data="documents" empty-text="当前目录暂无文档版本">
        <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
        <el-table-column prop="version" label="版本" width="110" />
        <el-table-column label="行业" width="100"><template #default="{ row }">{{ industryName(row.industry) }}</template></el-table-column>
        <el-table-column label="审核" width="130"><template #default="{ row }">{{ statuses[row.review_status as KnowledgeReviewStatus] || '未审核' }}</template></el-table-column>
        <el-table-column prop="source" label="来源" min-width="200" show-overflow-tooltip />
        <el-table-column label="操作" width="100"><template #default="{ row }">
          <el-button link type="primary" @click="openPreview(row.id)">查看版本</el-button>
        </template></el-table-column>
      </el-table>
      <p v-if="!auth.canManageKnowledge" class="hint">当前账号可查询和核对资料；上传、审核和停用由管理员处理。</p>
    </el-card>
    <el-card v-if="auth.canManageKnowledge" class="upload-card">
      <details ref="uploadDisclosure">
        <summary>{{ parentVersion ? `上传新版本：${parentVersion.title}` : '上传知识文档' }}</summary>
        <form class="doc-form" @submit.prevent="upload">
          <div class="doc-grid">
            <label>文档标题<input v-model="title" aria-label="文档标题" :maxlength="255" /></label>
            <label>原始来源链接<input v-model="source" aria-label="原始来源链接" :maxlength="2000" placeholder="发布前须提供可定位的 HTTP(S) 来源" /></label>
            <label>版本标识<input v-model="version" aria-label="版本标识" required :maxlength="64" placeholder="如：2026年修订版" /></label>
            <label>文档行业<select v-model="industry" aria-label="文档行业" :disabled="Boolean(parentVersion)">
              <option v-for="item in industries" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select></label>
          </div>
          <label>适用范围<textarea v-model="applicability" aria-label="适用范围" :maxlength="2000" rows="2" /></label>
          <label class="checkbox-label"><input v-model="isDemo" type="checkbox" />演示资料（不可发布为有效条款）</label>
          <label>文件（PDF / Word / Markdown / 纯文本）
            <input :key="fileKey" type="file" accept=".pdf,.docx,.md,.markdown,.txt" @change="onFileChange" />
          </label>
          <p class="hint">保存后为未审核版本。扫描件请先准备可提取文字的文件；更新原文请上传新版本。</p>
          <div class="doc-actions">
            <el-button native-type="submit" type="primary" :loading="store.loading" :disabled="!selectedFile || !version.trim() || !industries.length">保存待审核版本</el-button>
            <el-button v-if="parentVersion" @click="resetUpload">取消新版本</el-button>
            <el-button :loading="store.loading" @click="rebuild">重新构建索引</el-button>
          </div>
        </form>
      </details>
    </el-card>
    <el-card v-if="preview || detailLoading" class="detail-card">
      <section ref="detailSection" v-loading="detailLoading" tabindex="-1" aria-label="文档版本详情">
        <template v-if="preview">
          <header class="detail-header"><h2>{{ preview.title }} · {{ preview.version || '版本未标注' }}</h2>
            <span>{{ statuses[preview.review_status || 'unreviewed'] }}</span></header>
          <p>行业：{{ industryName(preview.industry) }} · 索引：{{ preview.status === 'indexed' ? '已构建' : preview.status === 'index_error' ? '构建失败，请重试' : '待构建' }}</p>
          <p>来源：<a v-if="sourceUrl" :href="sourceUrl" target="_blank" rel="noopener noreferrer">{{ preview.source }}</a><span v-else>{{ preview.source || '未注明' }}</span></p>
          <p>适用范围：{{ preview.applicability || '未注明，不能发布' }}</p>
          <p v-if="preview.is_demo" class="hint">演示资料，不作为有效条款。</p>
          <p class="identity">版本记录：{{ preview.id }}<br />内容 SHA256：{{ preview.content_sha256 || '旧资料未保存，请新建完整版本' }}</p>
          <div v-if="auth.canManageKnowledge" class="doc-actions">
            <el-button @click="newVersion(preview)">上传此文档的新版本</el-button>
            <el-button v-if="preview.review_status === 'unreviewed'" type="danger" plain @click="remove(preview.id)">删除未审核版本</el-button>
          </div>
          <h3>条款原文</h3>
          <ol class="article-list"><li v-for="article in articles?.items" :key="article.id">
            <strong>{{ article.article || '未编号条款' }} · {{ article.version }}</strong><p>{{ article.text }}</p>
          </li></ol>
          <div v-if="articles" class="doc-actions">
            <el-button :disabled="articles.offset === 0" @click="articlePage(Math.max(0, articles.offset - articles.limit))">上一页条款</el-button>
            <span>共 {{ articles.total }} 个条款切片</span>
            <el-button :disabled="articles.offset + articles.limit >= articles.total" @click="articlePage(articles.offset + articles.limit)">下一页条款</el-button>
          </div>
          <form v-if="auth.canManageKnowledge && ['unreviewed', 'approved'].includes(preview.review_status || 'unreviewed')"
            class="review-form" @submit.prevent="review">
            <h3>管理员审核</h3>
            <fieldset :disabled="reviewBusy">
              <label v-if="preview.review_status === 'unreviewed'">审核处理<select v-model="decision" aria-label="审核处理">
                <option value="approve">审核并发布</option><option value="reject">退回此版本</option>
              </select></label>
              <p v-else>停用后，此版本退出新检索；旧记录仍保留引用快照。</p>
              <label>审核意见<textarea v-model="reviewNote" aria-label="审核意见" required :maxlength="2000" rows="2" /></label>
              <label v-if="decision === 'approve'" class="checkbox-label">
                <input v-model="sourceChecked" type="checkbox" />已核对原始来源、版本、条款原文和适用范围
              </label>
              <el-button native-type="submit" type="primary" :loading="reviewBusy" :disabled="!reviewNote.trim() || decision === 'approve' && !sourceChecked">
                {{ decision === 'retire' ? '停用此版本' : decision === 'reject' ? '提交退回意见' : '审核并发布此版本' }}
              </el-button>
            </fieldset>
          </form>
          <section v-if="preview.review_history?.length" class="audit-history">
            <h3>审核记录</h3><ol><li v-for="(event, index) in preview.review_history" :key="index">
              {{ auditActions[event.action] || event.action }} · {{ event.actor || '未绑定个人身份' }} · {{ formatTime(event.at) }}<p>{{ event.note }}</p>
            </li></ol>
          </section>
        </template>
      </section>
    </el-card>
  </section>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api/client'
import { useAssessmentStore } from '../stores/assessment'
import { useAuthStore } from '../stores/auth'
import type { EvidenceItem, KnowledgeArticlePage, KnowledgeDocument, KnowledgeDocumentDetail,
  KnowledgeIndustry, KnowledgeReviewRequest, KnowledgeReviewStatus } from '../types'
import { extractError } from '../utils/errors'
import { formatTime } from '../utils/format'

const store = useAssessmentStore(), auth = useAuthStore()
const documents = ref<KnowledgeDocument[]>([])
const industries = ref<{ value: KnowledgeIndustry; label: string }[]>([])
const statuses: Record<KnowledgeReviewStatus, string> = { unreviewed: '未审核', approved: '已审核发布',
  rejected: '已退回', superseded: '已被新版本替代', retired: '已停用' }
const auditActions: Record<string, string> = { approve: '审核发布', reject: '退回', retire: '停用', superseded: '新版本替代' }
const industryFilter = ref<KnowledgeIndustry | ''>(''), statusFilter = ref<KnowledgeReviewStatus | ''>('')
const title = ref(''), source = ref(''), version = ref(''), applicability = ref('')
const industry = ref<KnowledgeIndustry>('general')
const isDemo = ref(false), selectedFile = ref<File | null>(null), fileKey = ref(0)
const parentVersion = ref<KnowledgeDocument | null>(null)
const uploadDisclosure = ref<HTMLDetailsElement>(), detailSection = ref<HTMLElement>()
const preview = ref<KnowledgeDocumentDetail | null>(null), articles = ref<KnowledgeArticlePage | null>(null)
const error = ref(''), listing = ref(false), detailLoading = ref(false), searching = ref(false)
const query = ref(''), searchResult = ref<{ items: EvidenceItem[]; notice: string } | null>(null)
const reviewNote = ref(''), sourceChecked = ref(false)
const decision = ref<KnowledgeReviewRequest['decision']>('approve')
const reviewBusy = computed(() => Boolean(preview.value && store.reviewPending[`knowledge:${preview.value.id}`]))
const sourceUrl = computed(() => /^https?:\/\//i.test(preview.value?.source || '') ? preview.value?.source : undefined)
let listSequence = 0, detailSequence = 0, searchSequence = 0
onUnmounted(() => { listSequence++; detailSequence++; searchSequence++ })
onMounted(initialize)
async function initialize() {
  error.value = ''
  try {
    const result = await api.get<{ industries: typeof industries.value }>('/knowledge/catalog')
    industries.value = result.data.industries
  } catch (err) { error.value = extractError(err) }
  await load()
}
function industryName(value?: string | null) { return industries.value.find(item => item.value === value)?.label || '未归类 / 通用' }
async function load() {
  const sequence = ++listSequence
  listing.value = true
  try {
    const rows = await store.listDocuments({ industry: industryFilter.value || undefined, review_status: statusFilter.value || undefined })
    if (sequence === listSequence) documents.value = rows
  } catch (err) { if (sequence === listSequence) error.value = extractError(err) }
  finally { if (sequence === listSequence) listing.value = false }
}
function clearSearch() { searchSequence++; searchResult.value = null; searching.value = false }
function filtersChanged() { clearSearch(); void load() }
function onFileChange(event: Event) { selectedFile.value = (event.target as HTMLInputElement).files?.[0] || null }
function resetUpload() {
  title.value = ''; source.value = ''; version.value = ''; applicability.value = ''
  industry.value = industryFilter.value || 'general'; isDemo.value = false
  selectedFile.value = null; parentVersion.value = null; fileKey.value++
}
async function upload() {
  if (!selectedFile.value || !version.value.trim() || store.loading) return
  error.value = ''
  try {
    const saved = await store.uploadDocument(selectedFile.value, title.value.trim() || selectedFile.value.name, source.value.trim(), {
      version: version.value.trim(), industry: industry.value, applicability: applicability.value.trim(), is_demo: isDemo.value,
      ...(parentVersion.value ? { supersedes_id: parentVersion.value.id } : {}),
    })
    if (saved.status === 'index_error') ElMessage.warning('版本已保存，但索引构建失败，请重试')
    else ElMessage.success('版本已保存，待人工审核')
    clearSearch(); resetUpload()
    if (uploadDisclosure.value) uploadDisclosure.value.open = false
    await load(); await openPreview(saved.id)
  } catch (err) { error.value = extractError(err) }
}
async function openPreview(id: string) {
  const sequence = ++detailSequence
  preview.value = null; detailLoading.value = true; error.value = ''
  try {
    const [document, page] = await Promise.all([store.getDocument(id), store.getArticles(id)])
    if (sequence !== detailSequence) return
    preview.value = document; articles.value = page; reviewNote.value = ''; sourceChecked.value = false
    decision.value = document.review_status === 'approved' ? 'retire' : 'approve'
    await nextTick(); detailSection.value?.scrollIntoView?.({ block: 'start' })
  } catch (err) { if (sequence === detailSequence) error.value = extractError(err) }
  finally { if (sequence === detailSequence) detailLoading.value = false }
}
async function articlePage(offset: number) {
  if (!preview.value) return
  const id = preview.value.id, sequence = detailSequence
  try {
    const page = await store.getArticles(id, offset)
    if (sequence === detailSequence && preview.value?.id === id) articles.value = page
  } catch (err) { error.value = extractError(err) }
}
async function newVersion(document: KnowledgeDocument) {
  resetUpload(); parentVersion.value = document; title.value = document.title; source.value = document.source || ''
  industry.value = document.industry || 'general'; applicability.value = document.applicability || ''
  await nextTick()
  if (uploadDisclosure.value) { uploadDisclosure.value.open = true; uploadDisclosure.value.scrollIntoView?.({ block: 'start' }) }
}
async function review() {
  if (!preview.value || reviewBusy.value || !reviewNote.value.trim() || decision.value === 'approve' && !sourceChecked.value) return
  const id = preview.value.id
  error.value = ''
  try {
    const saved = await store.reviewDocument(id, { decision: decision.value, note: reviewNote.value.trim(),
      source_checked: sourceChecked.value, revision: preview.value.revision ?? 0 })
    if (saved.status === 'index_error') ElMessage.warning('审核已保存，但索引失败，请管理员重建')
    else ElMessage.success('审核结果已保存')
    clearSearch()
    if (preview.value?.id === id) await openPreview(id)
    await load()
  } catch (err) { error.value = extractError(err) }
}
async function remove(id: string) {
  try { await store.deleteDocument(id); clearSearch(); if (preview.value?.id === id) preview.value = null; await load() }
  catch (err) { error.value = extractError(err) }
}
async function rebuild() {
  try { await store.rebuildKnowledge(); clearSearch(); ElMessage.success('索引已重新构建'); await load() }
  catch (err) { error.value = extractError(err) }
}
async function search() {
  if (!query.value.trim()) return
  const sequence = ++searchSequence
  searching.value = true; error.value = ''
  try {
    const result = await store.searchKnowledge(query.value.trim(), industryFilter.value || undefined)
    if (sequence === searchSequence) searchResult.value = result
  } catch (err) { if (sequence === searchSequence) error.value = extractError(err) }
  finally { if (sequence === searchSequence) searching.value = false }
}
</script>

<style scoped>
.knowledge-page { overflow-wrap: anywhere; }
h2 { font-size: var(--fs-md); margin: var(--s-3) 0; }
h3 { font-size: var(--fs-sm); margin: var(--s-4) 0 var(--s-2); }
.upload-card, .detail-card { margin-top: var(--s-4); }
.toolbar, .doc-actions, .detail-header { display: flex; flex-wrap: wrap; align-items: center; gap: var(--s-3); }
.toolbar { align-items: end; margin-bottom: var(--s-4); }
label { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.toolbar label { flex: 1; min-width: 130px; }
.toolbar .search-input { flex: 2; min-width: 180px; }
input:not([type=checkbox]), select, textarea { box-sizing: border-box; width: 100%; min-height: 40px; font: inherit;
  color: var(--text); background: var(--panel); border: 1px solid var(--border); border-radius: var(--r-control); padding: 8px; }
.doc-form, .review-form fieldset { display: flex; flex-direction: column; gap: var(--s-3); }
.doc-form { margin-top: var(--s-4); }
.doc-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr)); gap: var(--s-3); }
.checkbox-label { flex-direction: row; align-items: center; }
.review-form fieldset { margin: 0; padding: 0; border: 0; min-width: 0; }
.review-form button { align-self: flex-start; }
.hint, .identity { color: var(--muted); font-size: var(--fs-sm); }
.identity { overflow-wrap: anywhere; }
summary { cursor: pointer; font-weight: 600; }
.article-list, .search-results ol { padding-left: 24px; }
.article-list li, .search-results li { margin-block: var(--s-3); }
.article-list p { white-space: pre-wrap; }
a { color: var(--brand); }
@media (max-width: 760px) {
  input:not([type=checkbox]), select, textarea { font-size: 16px; }
  .toolbar label { min-width: 100%; }
}
</style>
