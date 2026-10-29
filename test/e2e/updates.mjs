/** M5: authoritative-source reminders and explainable trend alerts in the browser. */
import path from 'node:path'
import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import { assertNoHorizontalOverflow, launch } from './support.mjs'

const app = await launch('m5-updates')
const page = await app.browser.newPage({ viewport: { width: 1280, height: 900 } })
const now = new Date()
const target = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 1, 1))
const monthKey = date => `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`
const shift = (date, offset) => new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + offset, 1))

async function seed(month) {
  const form = new FormData()
  form.append('description', `M5_TEST_ONLY 电气线路隐患 ${monthKey(month)}`)
  form.append('mode', 'manual')
  form.append('facility', '配电室')
  form.append('scene', '配电房')
  form.append('event_time', `${monthKey(month)}-10T09:00:00+08:00`)
  form.append('data_source', 'report')
  const response = await app.request('POST', '/assessments', app.admin, form)
  if (![201, 202].includes(response.status)) throw new Error(await response.text())
  const payload = await response.json()
  const id = payload.assessment_id || payload.id
  await app.completed(id)
  const saved = await app.request('POST', `/assessments/${id}/classification`, app.admin, {
    category: '电气线路隐患', tags: [], risk_level: 1, note: 'M5_TEST_ONLY 人工核实',
    taxonomy_version: 'm1-v1', revision: 0,
  })
  assert.equal(saved.status, 200)
  const confirmed = await app.request('POST', `/assessments/${id}/confirm`, app.admin,
    { confirmed: true, edits: {} })
  assert.equal(confirmed.status, 200)
  return id
}

try {
  for (const offset of [6, 5, 4, 3, 2, 1]) await seed(shift(target, -offset))
  for (let index = 0; index < 5; index++) await seed(target)

  await app.login(page, 'browser-admin')
  await page.goto(app.frontendUrl + '/analytics')
  await page.getByRole('heading', { name: '管理分析', exact: true }).waitFor()
  const trendCard = page.locator('.section-card').filter({ hasText: '历史趋势提示' })
  await trendCard.getByRole('button', { name: '评估最新完整月份', exact: true }).click()
  const alertRow = trendCard.locator('tbody tr').filter({ hasText: '电气线路隐患' })
  await alertRow.waitFor()
  const alertText = await alertRow.innerText()
  assert.ok(alertText.includes('5 条') && alertText.includes('11 条') && alertText.includes('月均 1.0 条'))
  await trendCard.getByText('回测：评估 1 个月，触发 1 次').waitFor()
  await trendCard.getByText('误报记录 0 条', { exact: true }).waitFor()
  await trendCard.getByLabel('趋势处理备注', { exact: true }).fill('M5_TEST_ONLY 现场核查为集中排查')
  await alertRow.getByRole('button', { name: '标记误报', exact: true }).click()
  await trendCard.getByText('误报记录 1 条', { exact: true }).waitFor()
  await alertRow.getByText('误报', { exact: true }).waitFor()
  await trendCard.getByRole('button', { name: '评估最新完整月份', exact: true }).click()
  await trendCard.getByText('误报记录 1 条', { exact: true }).waitFor()
  assert.equal(await trendCard.locator('tbody tr').count(), 1)
  await assertNoHorizontalOverflow(page)
  await page.screenshot({ path: path.join(app.directory, 'trend-alerts-desktop.png'), fullPage: true, animations: 'disabled' })

  const documentsBefore = await (await app.request('GET', '/knowledge/documents', app.admin)).json()
  await page.goto(app.frontendUrl + '/knowledge')
  await page.getByRole('heading', { name: '知识库管理', exact: true }).waitFor()
  await page.getByRole('heading', { name: '权威来源更新提醒', exact: true }).waitFor()
  await page.getByLabel('来源名称', { exact: true }).fill('M5_TEST_ONLY 官方来源')
  await page.getByLabel('来源链接', { exact: true }).fill(`${app.backendUrl}/api/v1/health`)
  await page.getByRole('button', { name: '添加来源', exact: true }).click()
  const goodRow = page.locator('.source-table .el-table__row').filter({ hasText: 'M5_TEST_ONLY 官方来源' })
  await goodRow.waitFor()
  await goodRow.getByRole('button', { name: '检查', exact: true }).click()
  await goodRow.getByText('无变化', { exact: true }).waitFor()
  await goodRow.getByRole('button', { name: '检查', exact: true }).click()
  await goodRow.getByText('无变化', { exact: true }).waitFor()
  assert.equal(await page.getByText('待处理', { exact: true }).count(), 0)

  await page.getByLabel('来源名称', { exact: true }).fill('M5_TEST_ONLY 不可达来源')
  await page.getByLabel('来源链接', { exact: true }).fill('http://127.0.0.1:1/unreachable')
  await page.getByRole('button', { name: '添加来源', exact: true }).click()
  const badRow = page.locator('.source-table .el-table__row').filter({ hasText: 'M5_TEST_ONLY 不可达来源' })
  await badRow.waitFor()
  await badRow.getByRole('button', { name: '检查', exact: true }).click()
  await badRow.getByText('检查失败', { exact: true }).waitFor()
  await badRow.getByText(/来源(返回 HTTP|不可达)/).waitFor()
  const documentsAfter = await (await app.request('GET', '/knowledge/documents', app.admin)).json()
  assert.equal(documentsAfter.length, documentsBefore.length)
  await badRow.getByRole('button', { name: '删除', exact: true }).click()
  await badRow.waitFor({ state: 'detached' })
  await assertNoHorizontalOverflow(page)
  await page.screenshot({ path: path.join(app.directory, 'sources-desktop.png'), fullPage: true, animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  await assertNoHorizontalOverflow(page)
  await page.screenshot({ path: path.join(app.directory, 'sources-mobile.png'), fullPage: true, animations: 'disabled' })

  const inspector = await app.browser.newPage({ viewport: { width: 1280, height: 900 } })
  await app.login(inspector, 'browser-inspector')
  await inspector.goto(app.frontendUrl + '/knowledge')
  await inspector.getByRole('heading', { name: '知识库管理', exact: true }).waitFor()
  assert.equal(await inspector.getByRole('heading', { name: '权威来源更新提醒', exact: true }).count(), 0)

  await writeFile(path.join(app.directory, 'result.json'), JSON.stringify({
    passed: true,
    trendAlertShown: true, sampleSize: 11, backtestShown: true, falsePositiveRecorded: true,
    noDuplicateAlert: true, unchangedSourceNoReminder: true, unreachableVisible: true,
    noAutomaticPublication: true, sourceDeleted: true, inspectorReadOnly: true, desktopAndMobile: true,
  }, null, 2))
  console.log(JSON.stringify({ passed: true, directory: app.directory }))
} catch (error) {
  await page.screenshot({ path: path.join(app.directory, 'failure.png'), fullPage: true }).catch(() => {})
  await writeFile(path.join(app.directory, 'failure.txt'), String(error) + '\n' + app.logs())
  throw error
} finally {
  await app.close()
}
