/** R7/T18 real browser: approve, reject, edit, audit identity and role controls. */
import assert from 'node:assert/strict'
import path from 'node:path'
import { writeFile } from 'node:fs/promises'
import { launch } from './support.mjs'

const before = process.argv.includes('--before')
const app = await launch('r7-human-review')
let page
try {
  const context = await app.browser.newContext({ viewport: { width: 1280, height: 900 } })
  page = await context.newPage()
  await app.login(page, before ? 'browser-admin' : 'browser-reviewer')
  const item = await app.create()
  await page.goto(`${app.frontendUrl}/assessments/${item.id}`)
  await page.getByText('整改工单', { exact: true }).waitFor()
  if (before) {
    await page.screenshot({ path: path.join(app.directory, 'before-desktop.png'), fullPage: true })
    await page.setViewportSize({ width: 390, height: 844 })
    await page.screenshot({ path: path.join(app.directory, 'before-mobile.png'), fullPage: true })
  } else {
    let confirms = 0
    page.on('request', (request) => { if (request.url().endsWith('/confirm')) confirms++ })
    await page.locator('.review-form textarea').fill('已现场核实，批准')
    await page.locator('.review-form').evaluate((form) => { form.requestSubmit(); form.requestSubmit() })
    await page.getByText('已人工定稿。需要重新研判时，请新建关联记录。').waitFor()
    let saved = await (await app.request('GET', `/assessments/${item.id}`, app.admin)).json()
    assert.equal(confirms, 1)
    assert.equal(saved.human_review.history.length, 1)
    assert.equal(saved.human_review.resolution.reviewer, 'browser-reviewer')
    assert.equal(saved.human_review.ai_original.conclusion, item.conclusion)
    const reviewer = await app.token('browser-reviewer')
    const replay = await app.request('POST', `/assessments/${item.id}/confirm`, reviewer,
      { confirmed: true, edits: {}, note: '已现场核实，批准' })
    assert.equal(replay.status, 200)
    assert.equal((await replay.json()).human_review.history.length, 1)

    const editable = await app.create()
    await page.goto(`${app.frontendUrl}/assessments/${editable.id}`)
    await page.locator('label.el-radio-button').filter({ hasText: '拒绝当前结论' }).click()
    await page.getByRole('button', { name: '提交拒绝意见', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: '拒绝当前结论时，请填写复核意见。' }).waitFor()
    await page.locator('.review-form textarea').fill('现场证据与 AI 结论不一致')
    await page.getByRole('button', { name: '提交拒绝意见', exact: true }).click()
    await page.getByText('当前结论已拒绝，等待重新复核。').waitFor()
    saved = await (await app.request('GET', `/assessments/${editable.id}`, app.admin)).json()
    assert.equal(saved.status, 'needs_review')
    assert.equal(saved.confirmed, false)
    assert.equal(saved.human_review.history.length, 1)
    await page.locator('label.el-radio-button').filter({ hasText: '修订并定稿' }).click()
    await page.getByLabel('隐患类别', { exact: true }).fill('消防器材失效')
    await page.locator('.review-field .el-select').click()
    await page.getByRole('option', { name: '二级 · 限期整改', exact: true }).click()
    const conclusion = '人工核实为灭火器失效，按二级限期更换并复查。'
    await page.getByLabel('人工结论', { exact: true }).fill(conclusion)
    await page.locator('.review-form textarea').last().fill('已核对设备日期，修订类别和等级')
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path: path.join(app.directory, 'edit-desktop.png'), fullPage: true })
    await page.setViewportSize({ width: 390, height: 844 })
    await page.evaluate(() => window.scrollTo(0, 0))
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    await page.screenshot({ path: path.join(app.directory, 'edit-mobile.png'), fullPage: true })
    await page.setViewportSize({ width: 1280, height: 900 })
    await page.getByRole('button', { name: '保存修订并定稿', exact: true }).click()
    await page.getByText('已人工定稿。需要重新研判时，请新建关联记录。').waitFor()
    saved = await (await app.request('GET', `/assessments/${editable.id}`, app.admin)).json()
    assert.equal(saved.risk_level, 2)
    assert.equal(saved.hazard_category, '消防器材失效')
    assert.equal(saved.report.summary, conclusion)
    assert.equal(saved.report.work_order.category, '消防器材失效')
    assert.equal(saved.report.work_order.level, '2 级')
    assert.equal(saved.human_review.history.length, 2)
    assert.equal(saved.human_review.ai_original.conclusion, editable.conclusion)
    assert.equal(saved.human_review.history[1].before.hazard_category, editable.hazard_category)
    const exported = await (await app.request('GET', `/assessments/${editable.id}/export`, reviewer)).json()
    assert.ok(exported.content.includes(conclusion) && exported.content.includes('消防器材失效'))
    await page.getByText('AI 原始结论与规则结果', { exact: true }).click()
    assert.ok(await page.locator('.conclusion-title').innerText().then((text) => text.includes('消防器材失效')))
    await page.screenshot({ path: path.join(app.directory, 'after-desktop.png'), fullPage: true })
    await page.setViewportSize({ width: 390, height: 844 })
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    await page.screenshot({ path: path.join(app.directory, 'after-mobile.png'), fullPage: true })
    const inspectorContext = await app.browser.newContext()
    const inspectorPage = await inspectorContext.newPage()
    await app.login(inspectorPage, 'browser-inspector')
    await inspectorPage.goto(`${app.frontendUrl}/assessments/${(await app.create()).id}`)
    await inspectorPage.getByText('当前账号可查看结果，请复核员或管理员处理。').waitFor()
    assert.equal(await inspectorPage.locator('.review-form').count(), 0)
    const inspector = await app.token('browser-inspector')
    const forbidden = await app.request('POST', `/assessments/${editable.id}/confirm`, inspector, { confirmed: true })
    assert.equal(forbidden.status, 403)
    await writeFile(path.join(app.directory, 'result.json'), JSON.stringify({ passed: true,
      provider: 'mock', browser: process.platform === 'win32' ? 'Edge headless' : 'Chromium headless',
      approved_id: item.id, revised_id: editable.id, approve_post_count: 1,
      rejection_requires_note: true, revision_history_count: 2, export_consistent: true,
      inspector_ui_hidden_and_api_403: true, mobile_viewport_emulated: true }, null, 2))
  }
  console.log(`R7 review ${before ? 'before screenshots' : 'passed'}: ${app.directory}`)
} catch (error) {
  if (page) await page.screenshot({ path: path.join(app.directory, 'failure.png'), fullPage: true }).catch(() => {})
  await writeFile(path.join(app.directory, 'failure.log'), String(error) + '\n' + app.logs())
  throw error
} finally {
  await app.close()
}
