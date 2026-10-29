/** M6: lab timing for query, entry, Mock classification and review including one correction. */
import path from 'node:path'
import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import { launch } from './support.mjs'

const app = await launch('m6-timing')
const inspector = await app.browser.newPage({ viewport: { width: 1280, height: 900 } })
const reviewer = await app.browser.newPage({ viewport: { width: 1280, height: 900 } })
const timings = {}

try {
  const documentForm = new FormData()
  documentForm.append('title', 'M6_TEST_ONLY 计时规范')
  documentForm.append('source', 'https://example.test/m6-timing')
  documentForm.append('version', 'v1')
  documentForm.append('industry', 'fire')
  documentForm.append('applicability', 'M6_TEST_ONLY 计时场景')
  documentForm.append('file', new Blob(['第一条 M6 测试条款：疏散通道应保持畅通。'], { type: 'text/plain' }), 'timing.txt')
  const uploaded = await app.request('POST', '/knowledge/documents', app.admin, documentForm)
  assert.equal(uploaded.status, 201)
  const doc = await uploaded.json()
  const approved = await app.request('POST', `/knowledge/documents/${doc.id}/review`, app.admin, {
    decision: 'approve', revision: doc.revision, source_checked: true, note: 'M6_TEST_ONLY 计时审核',
  })
  assert.equal(approved.status, 200)

  await app.login(inspector, 'browser-inspector')
  await app.login(reviewer, 'browser-reviewer')

  await inspector.goto(app.frontendUrl + '/knowledge')
  await inspector.getByLabel('条款关键词', { exact: true }).fill('疏散通道')
  let started = Date.now()
  await inspector.getByRole('button', { name: '检索已审核条款', exact: true }).click()
  await inspector.locator('.search-results li').first().waitFor()
  timings.queryMs = Date.now() - started

  await inspector.goto(app.frontendUrl + '/')
  await inspector.getByText('仅人工录入', { exact: true }).click()
  await inspector.locator('#hazard-description').fill('M6_TEST_ONLY 楼道堆物，影响疏散')
  const accepted = inspector.waitForResponse(response =>
    response.url().endsWith('/api/v1/assessments') && response.request().method() === 'POST')
  started = Date.now()
  await inspector.getByRole('button', { name: '创建人工记录', exact: true }).click()
  const acceptedResponse = await accepted
  assert.ok([201, 202].includes(acceptedResponse.status()))
  const payload = await acceptedResponse.json()
  const id = payload.assessment_id || payload.id
  await app.completed(id)
  await inspector.getByLabel('最终类别', { exact: true }).waitFor()
  await inspector.getByLabel('最终类别', { exact: true }).selectOption('占用疏散通道')
  await inspector.getByLabel('现场核实备注（可选）', { exact: true }).fill('M6_TEST_ONLY 初次录入')
  const saveStarted = Date.now()
  await inspector.getByRole('button', { name: '保存人工录入', exact: true }).click()
  await inspector.getByText('人工录入已保存，待审核。', { exact: true }).waitFor()
  const saveMs = Date.now() - saveStarted
  timings.entryMs = Date.now() - started
  timings.entrySaveMs = saveMs

  await reviewer.goto(`${app.frontendUrl}/assessments/${id}`)
  await reviewer.getByText('拒绝当前结论', { exact: true }).click()
  await reviewer.locator('.review-form textarea').fill('M6_TEST_ONLY 类别需按现场更正')
  started = Date.now()
  await reviewer.getByRole('button', { name: '提交拒绝意见', exact: true }).click()
  await reviewer.getByText('当前结论已拒绝，等待重新复核。', { exact: true }).waitFor()
  timings.rejectMs = Date.now() - started

  await inspector.goto(`${app.frontendUrl}/assessments/${id}`)
  await inspector.getByLabel('最终类别', { exact: true }).waitFor()
  await inspector.getByLabel('最终类别', { exact: true }).selectOption('消防器材失效')
  await inspector.getByLabel('现场核实备注（可选）', { exact: true }).fill('M6_TEST_ONLY 复核后更正类别')
  started = Date.now()
  await inspector.getByRole('button', { name: '保存人工录入', exact: true }).click()
  await inspector.getByText('人工录入已保存，待审核。', { exact: true }).waitFor()
  timings.correctionMs = Date.now() - started

  await reviewer.goto(`${app.frontendUrl}/assessments/${id}`)
  await reviewer.getByRole('button', { name: '批准并定稿', exact: true }).waitFor()
  await reviewer.locator('.review-form textarea').fill('M6_TEST_ONLY 更正后批准')
  started = Date.now()
  await reviewer.getByRole('button', { name: '批准并定稿', exact: true }).click()
  await reviewer.getByText('已人工定稿。需要重新研判时，请新建关联记录。', { exact: true }).waitFor()
  timings.approveMs = Date.now() - started
  timings.reviewMs = timings.rejectMs + timings.correctionMs + timings.approveMs

  await inspector.goto(app.frontendUrl + '/')
  await inspector.getByText('AI 分类助手', { exact: true }).click()
  await inspector.locator('#hazard-description').fill('M6_TEST_ONLY 计时分类：楼道纸箱堵塞疏散通道')
  started = Date.now()
  await inspector.getByRole('button', { name: '生成分类建议', exact: true }).click()
  await inspector.getByRole('button', { name: '采用建议填写', exact: true }).waitFor({ timeout: 30000 })
  timings.classificationMs = Date.now() - started

  timings.totalMs = timings.classificationMs + timings.queryMs + timings.entryMs + timings.reviewMs
  const result = {
    passed: true,
    mode: 'mock',
    note: '工程基线：分类使用 Mock，不代表真实模型质量或业务收益；总耗时含一次复核退回与人工更正。',
    ...timings,
  }
  await writeFile(path.join(app.directory, 'timing.json'), JSON.stringify(result, null, 2))
  console.log(JSON.stringify({ passed: true, directory: app.directory, ...timings }))
} catch (error) {
  await inspector.screenshot({ path: path.join(app.directory, 'failure.png'), fullPage: true }).catch(() => {})
  await writeFile(path.join(app.directory, 'failure.txt'), String(error) + '\n' + app.logs())
  throw error
} finally {
  await app.close()
}
