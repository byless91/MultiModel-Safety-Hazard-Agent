import ElementPlus, { ElMessage } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { apiMock } = vi.hoisted(() => ({ apiMock: { post: vi.fn(), get: vi.fn(), delete: vi.fn() } }))
vi.mock('../../frontend/src/api/client', () => ({
  api: apiMock, getStoredToken: () => null, setStoredToken: () => undefined,
}))
import KnowledgeView from '../../frontend/src/views/KnowledgeView.vue'
import { useAuthStore } from '../../frontend/src/stores/auth'
import type { KnowledgeDocumentDetail } from '../../frontend/src/types'

const industries = [{ value: 'general', label: '通用' }, { value: 'fire', label: '消防' },
  { value: 'forest', label: '林区' }, { value: 'community', label: '社区' }, { value: 'production', label: '安全生产' }]
let serverDoc: KnowledgeDocumentDetail
const wrappers: ReturnType<typeof mount>[] = []
const buttons = (wrapper: ReturnType<typeof mount>, name: string) => wrapper.findAll('button').find(b => b.text() === name)!
async function page(role = 'admin') {
  const auth = useAuthStore()
  auth.authMode = 'jwt'; auth.credentialValid = true
  auth.user = { id: role, username: role, role }
  const wrapper = mount(KnowledgeView, { global: { plugins: [ElementPlus] } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
async function detail(wrapper: ReturnType<typeof mount>) {
  await buttons(wrapper, '查看版本').trigger('click')
  await flushPromises()
}
beforeEach(() => {
  vi.resetAllMocks(); setActivePinia(createPinia())
  serverDoc = { id: 'document-v1', title: '测试消防资料', version: 'v1', source: 'https://example.test/source',
    status: 'indexed', created_at: '2026-10-29T00:00:00Z', content: '第一条 测试条款', industry: 'fire',
    applicability: '测试场景', review_status: 'unreviewed', revision: 0, content_sha256: 'a'.repeat(64),
    series_id: 'document-v1', review_history: [] }
  apiMock.get.mockImplementation(async (url: string) => {
    if (url === '/knowledge/catalog') return { data: { industries } }
    if (url === '/knowledge/documents') return { data: [serverDoc] }
    if (url.endsWith('/articles')) return { data: { items: [{ id: 'chunk-1', article: '第一条', version: 'v1', text: '第一条 测试条款' }], offset: 0, limit: 30, total: 1 } }
    if (url === '/knowledge/search') return { data: { items: [], notice: '未找到已审核的有效条款' } }
    return { data: serverDoc }
  })
})
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); vi.restoreAllMocks(); document.body.innerHTML = '' })

describe('M2 original knowledge page', () => {
  it('requires an explicit source check before approval and submits the current revision', async () => {
    const wrapper = await page()
    await detail(wrapper)
    expect(wrapper.text()).toContain(serverDoc.content_sha256)
    await wrapper.get('[aria-label="审核意见"]').setValue('已核对测试材料')
    await wrapper.get('.review-form').trigger('submit')
    expect(apiMock.post).not.toHaveBeenCalled()
    await wrapper.get('.review-form input[type=checkbox]').setValue(true)
    apiMock.post.mockImplementationOnce(async () => {
      serverDoc = { ...serverDoc, review_status: 'approved', revision: 1 }
      return { data: serverDoc }
    })
    await wrapper.get('.review-form').trigger('submit')
    await flushPromises()
    expect(apiMock.post.mock.calls[0]).toEqual(['/knowledge/documents/document-v1/review', {
      decision: 'approve', note: '已核对测试材料', source_checked: true, revision: 0,
    }])
    expect(wrapper.text()).toContain('已审核发布')
    expect(buttons(wrapper, '停用此版本')).toBeDefined()
  })

  it.each(['inspector', 'reviewer'])('allows %s reading but hides management actions', async role => {
    const wrapper = await page(role)
    await detail(wrapper)
    expect(wrapper.find('.upload-card').exists()).toBe(false)
    expect(wrapper.find('.review-form').exists()).toBe(false)
    expect(wrapper.text()).toContain('第一条 测试条款')
    expect(wrapper.text()).toContain('上传、审核和停用由管理员处理')
  })

  it('uploads a distinct new version and never edits the selected version in place', async () => {
    const wrapper = await page()
    await detail(wrapper)
    await buttons(wrapper, '上传此文档的新版本').trigger('click')
    expect(wrapper.get('[aria-label="文档行业"]').attributes('disabled')).toBeDefined()
    await wrapper.get('[aria-label="版本标识"]').setValue('v2')
    const file = new File(['第二版测试原文'], 'v2.txt', { type: 'text/plain' })
    const input = wrapper.get('input[type=file]')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    apiMock.post.mockImplementationOnce(async () => {
      serverDoc = { ...serverDoc, id: 'document-v2', version: 'v2', supersedes_id: 'document-v1' }
      return { data: serverDoc }
    })
    await wrapper.get('.doc-form').trigger('submit')
    await flushPromises()
    const form = apiMock.post.mock.calls[0][1] as FormData
    expect(form.get('supersedes_id')).toBe('document-v1')
    expect(form.get('version')).toBe('v2')
    expect(form.get('industry')).toBe('fire')
    const uploaded = form.get('file') as File
    expect(uploaded.name).toBe('v2.txt')
    expect(await uploaded.text()).toBe('第二版测试原文')
    expect(wrapper.text()).toContain('测试消防资料 · v2')
  })

  it('shows no-approved-result explicitly and submits the selected industry', async () => {
    const wrapper = await page()
    await wrapper.get('[aria-label="行业目录"]').setValue('forest')
    await wrapper.get('[aria-label="条款关键词"]').setValue('林区用火')
    await wrapper.get('.toolbar').trigger('submit')
    await flushPromises()
    expect(apiMock.get).toHaveBeenCalledWith('/knowledge/search', { params: { query: '林区用火', industry: 'forest' } })
    expect(wrapper.text()).toContain('未找到已审核的有效条款')
  })

  it('does not announce a successful index when the upload was saved with index_error', async () => {
    const wrapper = await page()
    const warning = vi.spyOn(ElMessage, 'warning')
    await wrapper.get('[aria-label="版本标识"]').setValue('v1')
    const input = wrapper.get('input[type=file]')
    Object.defineProperty(input.element, 'files', { value: [new File(['测试内容'], 'law.txt')], configurable: true })
    await input.trigger('change')
    apiMock.post.mockResolvedValueOnce({ data: { ...serverDoc, status: 'index_error' } })
    await wrapper.get('.doc-form').trigger('submit')
    await flushPromises()
    expect(warning).toHaveBeenCalledWith('版本已保存，但索引构建失败，请重试')
  })

  it('ignores an old industry response after the user changes the filter again', async () => {
    const wrapper = await page()
    let finishOld!: (value: unknown) => void
    const old = new Promise(resolve => { finishOld = resolve })
    apiMock.get.mockImplementation((url: string, options?: { params?: { industry?: string } }) => {
      if (url === '/knowledge/documents' && options?.params?.industry === 'forest') return old
      return Promise.resolve({ data: [{ ...serverDoc, title: '新的消防筛选结果' }] })
    })
    await wrapper.get('[aria-label="行业目录"]').setValue('forest')
    await wrapper.get('[aria-label="行业目录"]').setValue('fire')
    await flushPromises()
    finishOld({ data: [{ ...serverDoc, title: '过期的林区结果' }] })
    await flushPromises()
    expect(wrapper.text()).toContain('新的消防筛选结果')
    expect(wrapper.text()).not.toContain('过期的林区结果')
  })

  it('refreshes index status after rebuilding without discarding an unfinished review note', async () => {
    serverDoc.status = 'index_error'
    const wrapper = await page()
    await detail(wrapper)
    await wrapper.get('[aria-label="审核意见"]').setValue('正在核对，请保留备注')
    expect(wrapper.text()).toContain('构建失败，请重试')
    apiMock.post.mockImplementationOnce(async () => {
      serverDoc = { ...serverDoc, status: 'indexed' }
      return { data: { records: 1, chunks: 1, embedding_fallback: false } }
    })
    await buttons(wrapper, '重新构建索引').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('索引：已构建')
    expect(wrapper.text()).not.toContain('构建失败，请重试')
    expect((wrapper.get('[aria-label="审核意见"]').element as HTMLTextAreaElement).value).toBe('正在核对，请保留备注')
  })
})
