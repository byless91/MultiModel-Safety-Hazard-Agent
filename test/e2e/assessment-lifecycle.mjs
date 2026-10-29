/** R7/T20 real UI + isolated Mock API, three roles and a complete image lifecycle. */
import assert from 'node:assert/strict'
import path from 'node:path'
import { readFile, writeFile } from 'node:fs/promises'
import { assertNoHorizontalOverflow, launch, root } from './support.mjs'

const app = await launch('r7-assessment-lifecycle')
const pages = []
try {
  async function actor(username) {
    const context = await app.browser.newContext({ viewport: { width: 1280, height: 900 }, acceptDownloads: true })
    const page = await context.newPage()
    pages.push(page)
    await app.login(page, `browser-${username}`)
    return page
  }
  const inspector = await actor('inspector')
  const reviewer = await actor('reviewer')
  const admin = await actor('admin')
  const inspectorToken = await app.token('browser-inspector')
  const statuses = []
  // Keep exercising the historical follow-up/rectification flow via its compatible API.
  // The default homepage classification upload is covered by classification.mjs.
  const initial = new FormData()
  initial.append('description', '现场情况不清楚')
  initial.append('mode', 'assessment')
  initial.append('files', new Blob([await readFile(path.join(root, 'test/evaluation/images/fire-hazard.png'))],
    { type: 'image/png' }), 'fire-hazard.png')
  const response = await app.request('POST', '/assessments', inspectorToken, initial)
  assert.equal(response.status, 202)
  const initialJob = await response.json()
  const id = initialJob.assessment_id
  await inspector.goto(`${app.frontendUrl}/assessments/${id}`)
  const endpoint = `/assessments/${id}`
  const fetchItem = async () => (await app.request('GET', endpoint, app.admin)).json()
  await inspector.getByRole('button', { name: '提交补充信息', exact: true }).waitFor({ timeout: 30000 })
  let item = await fetchItem()
  assert.equal(item.status, 'needs_more_info')
  assert.equal(item.images.filter((image) => image.image_kind === 'original').length, 1)
  statuses.push(item.status)
  await inspector.getByPlaceholder('补充隐患位置、危险程度、现场环境等信息')
    .fill('安全出口被纸箱杂物堵塞，疏散通道无法通行，需立即清理')
  await inspector.getByRole('button', { name: '提交补充信息', exact: true }).click()
  await inspector.getByText('当前账号可查看结果，请复核员或管理员处理。').waitFor({ timeout: 30000 })
  item = await fetchItem()
  assert.equal(item.status, 'awaiting_human_review')
  assert.equal(item.followup_used, 1)
  const followupJob = await (await app.request('GET', endpoint + '/job', app.admin)).json()
  assert.equal(followupJob.kind, 'followup')
  assert.equal(followupJob.status, 'succeeded')
  statuses.push(item.status)
  assert.equal((await app.request('POST', endpoint + '/confirm', inspectorToken, { confirmed: true })).status, 403)

  await reviewer.goto(`${app.frontendUrl}/assessments/${id}`)
  await reviewer.locator('label.el-radio-button').filter({ hasText: '修订并定稿' }).click()
  await reviewer.getByLabel('隐患类别', { exact: true }).fill('占用疏散通道')
  await reviewer.locator('.review-field .el-select').click()
  await reviewer.getByRole('option', { name: '一级 · 立即处置', exact: true }).click()
  await reviewer.getByLabel('人工结论', { exact: true }).fill('人工核实出口被杂物堵塞，应立即清理并复查。')
  await reviewer.locator('.review-form textarea').last().fill('现场核对后修订 AI 待确认类别和等级')
  await reviewer.getByRole('button', { name: '保存修订并定稿', exact: true }).click()
  await reviewer.getByText('已人工定稿。需要重新研判时，请新建关联记录。').waitFor()
  item = await fetchItem()
  assert.equal(item.status, 'confirmed')
  assert.equal(item.human_review.resolution.reviewer, 'browser-reviewer')
  assert.equal(item.human_review.history.length, 1)
  assert.equal(item.hazard_category, '占用疏散通道')
  assert.equal(item.risk_level, 1)
  assert.equal(item.report.work_order.category, '占用疏散通道')
  assert.equal(item.report.work_order.level, '1 级')
  statuses.push(item.status)
  await reviewer.getByRole('tab', { name: /整改闭环/ }).click()
  await reviewer.getByRole('button', { name: '开始整改', exact: true }).click()
  await reviewer.getByText('已开始整改', { exact: true }).waitFor()
  assert.equal((await fetchItem()).rectification_status, 'rectifying')
  statuses.push('rectifying')

  await inspector.goto(`${app.frontendUrl}/assessments/${id}`)
  await inspector.getByRole('tab', { name: /整改闭环/ }).click()
  assert.equal(await inspector.getByRole('button', { name: '确认整改完成', exact: true }).count(), 0)
  await inspector.locator('.rect-form input[type=file]').setInputFiles(path.join(root, 'test/evaluation/images/fire-safe.png'))
  await inspector.getByPlaceholder('整改说明（可选）').fill('已完成清理和移除杂物，通道恢复畅通，隐患已消除')
  await inspector.getByRole('button', { name: '提交整改照片', exact: true }).click()
  await inspector.getByText('整改照片已提交', { exact: true }).waitFor()
  item = await fetchItem()
  assert.equal(item.rectification_status, 'pending_verification')
  assert.equal(item.images.filter((image) => image.image_kind === 'rectification').length, 1)
  assert.equal(item.rectification_analysis.comparison.pair_count, 1)
  assert.ok(item.rectification_score >= 0.8)
  assert.equal(item.rectification_status, 'pending_verification', 'AI recommendations cannot perform human verification')
  statuses.push(item.rectification_status)
  assert.equal((await app.request('POST', endpoint + '/rectification/transition', inspectorToken,
    { to_status: 'verified' })).status, 403)

  await reviewer.reload()
  await reviewer.getByRole('tab', { name: /整改闭环/ }).click()
  await reviewer.getByRole('button', { name: '确认整改完成', exact: true }).click()
  await reviewer.getByText('已确认整改完成', { exact: true }).waitFor()
  item = await fetchItem()
  assert.equal(item.rectification_status, 'verified')
  assert.equal(item.rectification_meta.history.at(-1).by, 'browser-reviewer')
  statuses.push(item.rectification_status)

  await admin.goto(`${app.frontendUrl}/assessments/${id}`)
  await admin.getByRole('tab', { name: /整改闭环/ }).click()
  let rejectedOnce = false
  await admin.route(`**/assessments/${id}/rectification/transition`, async (route) => {
    if (!rejectedOnce) {
      rejectedOnce = true
      await route.fulfill({ status: 403, json: { detail: '测试权限变化：关闭未保存，请核对后重试' } })
    } else await route.continue()
  })
  await admin.getByRole('button', { name: '关闭工单', exact: true }).click()
  await admin.getByText('测试权限变化：关闭未保存，请核对后重试', { exact: true }).waitFor()
  assert.equal((await fetchItem()).rectification_status, 'verified')
  await admin.getByRole('button', { name: '关闭工单', exact: true }).click()
  await admin.getByText('工单已关闭', { exact: true }).waitFor()
  item = await fetchItem()
  assert.equal(item.rectification_status, 'closed')
  assert.equal(item.rectification_meta.history.at(-1).by, 'browser-admin')
  assert.equal(item.rectification_meta.history.filter((event) => event.to_status === 'closed').length, 1)
  statuses.push(item.rectification_status)
  const downloadEvent = admin.waitForEvent('download')
  await admin.getByRole('button', { name: '下载报告', exact: true }).click()
  const download = await downloadEvent
  const exportPath = path.join(app.directory, 'downloaded-report.md')
  await download.saveAs(exportPath)
  const content = await readFile(exportPath, 'utf8')
  assert.ok(content.includes(item.conclusion) && content.includes(item.hazard_category))
  await admin.evaluate(() => window.scrollTo(0, 0))
  await admin.screenshot({ path: path.join(app.directory, 'closed-desktop.png'), fullPage: true })
  await admin.setViewportSize({ width: 390, height: 844 })
  await admin.evaluate(() => window.scrollTo(0, 0))
  await assertNoHorizontalOverflow(admin)
  await admin.screenshot({ path: path.join(app.directory, 'closed-mobile.png'), fullPage: true })
  await admin.getByRole('button', { name: '切换到暗色模式' }).click()
  await admin.screenshot({ path: path.join(app.directory, 'closed-mobile-dark.png'), fullPage: true })
  await writeFile(path.join(app.directory, 'result.json'), JSON.stringify({ passed: true,
    provider: 'mock', synthetic_image_fixtures: true, assessment_id: id, statuses,
    role_separation: ['inspector-submit-and-upload', 'reviewer-approve-and-verify', 'admin-close'],
    followup_job_id: followupJob.id, followup_used: 1, human_review_events: 1,
    rectification_history: item.rectification_meta.history, failed_close_preserved_state: true,
    downloaded_report_consistent: true, mobile_viewport_emulated: true, real_model_calls: 0 }, null, 2))
  console.log(`R7 lifecycle passed: ${app.directory}`)
} catch (error) {
  for (const [index, page] of pages.entries()) {
    await page.screenshot({ path: path.join(app.directory, `failure-${index}.png`), fullPage: true }).catch(() => {})
  }
  await writeFile(path.join(app.directory, 'failure.log'), String(error) + '\n' + app.logs())
  throw error
} finally {
  await app.close()
}
