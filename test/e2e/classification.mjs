/** M1: real browser, isolated API, image upload, manual entry, review and export. */
import assert from 'node:assert/strict'
import path from 'node:path'
import { readFile, writeFile } from 'node:fs/promises'
import { assertNoHorizontalOverflow, launch, root } from './support.mjs'

const app = await launch('m1-classification')
const inspector = await app.browser.newPage({ viewport: { width: 1280, height: 900 } })
try {
  await app.login(inspector, 'browser-inspector')
  await inspector.locator('input[type=file]').setInputFiles(path.join(root, 'test/evaluation/images/fire-hazard.png'))
  await inspector.locator('#hazard-description').fill('安全出口被纸箱堵塞，疏散通道无法通行')
  const accepted = inspector.waitForResponse(r => r.url().endsWith('/api/v1/assessments') && r.request().method() === 'POST')
  await inspector.getByRole('button', { name: '生成分类建议', exact: true }).click()
  const response = await accepted
  assert.equal(response.status(), 202)
  const job = await response.json()
  const id = job.assessment_id
  const getItem = async () => (await app.request('GET', `/assessments/${id}`, app.admin)).json()
  await inspector.getByRole('button', { name: '采用建议填写', exact: true }).waitFor({ timeout: 30000 })
  let item = await getItem()
  assert.equal(item.classification.suggested_category, '占用疏散通道')
  assert.equal(item.hazard_category, null)
  assert.equal(item.risk_level, null)
  assert.equal(item.report, null)
  assert.equal(item.classification.is_demo, true)
  await inspector.waitForFunction(() => document.querySelector('.scene-images img')?.naturalWidth > 0)
  await inspector.getByRole('button', { name: '采用建议填写', exact: true }).click()
  await inspector.getByLabel('最终类别', { exact: true }).selectOption('消防器材失效')
  await inspector.getByLabel('设施损坏', { exact: true }).check()
  await inspector.getByLabel('现场核实备注（可选）', { exact: true }).fill('人工核实为消防器材损坏，原建议仅供参考')
  let saves = 0
  inspector.on('request', r => { if (r.url().endsWith(`/${id}/classification`) && r.method() === 'POST') saves++ })
  await inspector.locator('.classification-form').evaluate(form => { form.requestSubmit(); form.requestSubmit() })
  await inspector.getByText('人工录入已保存，待审核。', { exact: true }).waitFor()
  assert.equal(saves, 1)
  item = await getItem()
  assert.equal(item.hazard_category, '消防器材失效')
  assert.equal(item.risk_level, null)
  assert.equal(item.confirmed, false)
  assert.ok(item.classification.final_tags.includes('设施损坏'))
  assert.equal(item.human_review.history[0].reviewer, 'browser-inspector')
  assert.equal(await inspector.getByRole('button', { name: '批准并定稿', exact: true }).count(), 0)
  await inspector.goto(`${app.frontendUrl}/assessments/${id}`)
  await inspector.getByLabel('最终类别', { exact: true }).waitFor()
  await inspector.waitForFunction(() => !document.querySelector('.classification-form fieldset')?.disabled)
  assert.equal(await inspector.getByLabel('最终类别', { exact: true }).inputValue(), '消防器材失效')
  await assertNoHorizontalOverflow(inspector)
  await inspector.screenshot({ path: path.join(app.directory, 'entry-desktop.png'), fullPage: true })
  await inspector.setViewportSize({ width: 390, height: 844 })
  await assertNoHorizontalOverflow(inspector)
  await inspector.screenshot({ path: path.join(app.directory, 'entry-mobile.png'), fullPage: true })

  const reviewer = await app.browser.newPage({ viewport: { width: 1280, height: 900 }, acceptDownloads: true })
  await app.login(reviewer, 'browser-reviewer')
  await reviewer.goto(`${app.frontendUrl}/assessments/${id}`)
  await reviewer.getByRole('button', { name: '批准并定稿', exact: true }).waitFor()
  await reviewer.locator('.review-form textarea').fill('已现场核实并确认分类，未填写风险等级')
  await reviewer.getByRole('button', { name: '批准并定稿', exact: true }).click()
  await reviewer.getByText('已人工定稿。需要重新研判时，请新建关联记录。').waitFor()
  item = await getItem()
  assert.equal(item.confirmed, true)
  assert.equal(item.risk_level, null)
  assert.equal(item.human_review.history.length, 2)
  assert.equal(item.human_review.resolution.reviewer, 'browser-reviewer')
  assert.equal(item.classification.suggested_category, '占用疏散通道')
  assert.equal(await reviewer.getByRole('button', { name: '保存人工录入', exact: true }).count(), 0)
  const downloadEvent = reviewer.waitForEvent('download')
  await reviewer.getByRole('button', { name: '导出分类记录', exact: true }).click()
  const download = await downloadEvent
  const exported = path.join(app.directory, 'classification-record.md')
  await download.saveAs(exported)
  const markdown = await readFile(exported, 'utf8')
  assert.ok(markdown.includes('未分级') && markdown.includes('人工类别：消防器材失效'))
  assert.ok(markdown.includes('AI 建议类别：占用疏散通道'))
  await reviewer.goto(`${app.frontendUrl}/history`)
  await reviewer.getByRole('cell', { name: '消防器材失效', exact: true }).waitFor()
  await reviewer.getByRole('cell', { name: '未分级', exact: true }).waitFor()

  await inspector.setViewportSize({ width: 1280, height: 900 })
  await inspector.goto(app.frontendUrl)
  await inspector.locator('label.el-radio-button').filter({ hasText: '仅人工录入' }).click()
  await inspector.locator('#hazard-description').fill('人工录入现场情况，暂不能识别具体类型')
  await inspector.getByRole('button', { name: '创建人工记录', exact: true }).click()
  await inspector.getByText('仅人工录入，未请求 AI 分类', { exact: true }).waitFor()
  await inspector.getByLabel('最终类别', { exact: true }).selectOption('其他隐患')
  await inspector.getByRole('button', { name: '保存人工录入', exact: true }).click()
  await inspector.getByText('人工录入已保存，待审核。', { exact: true }).waitFor()
  await writeFile(path.join(app.directory, 'result.json'), JSON.stringify({ passed: true, assessmentId: id,
    imageUploaded: true, suggestionSeparated: true, noAutomaticRisk: true, inspectorEntry: true,
    reviewerApproval: true, restoredAfterReload: true, duplicateSaveBlocked: true,
    exportVerified: true, historyVerified: true, manualEntry: true, desktopAndMobile: true }, null, 2))
  console.log(JSON.stringify({ passed: true, directory: app.directory, assessmentId: id }))
} catch (error) {
  await inspector.screenshot({ path: path.join(app.directory, 'failure.png'), fullPage: true }).catch(() => {})
  await writeFile(path.join(app.directory, 'failure.txt'), String(error) + '\n' + app.logs())
  throw error
} finally {
  await app.close()
}
