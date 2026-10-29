/** M3: manual location entry, separated event time and deduplicated imports. */
import path from 'node:path'
import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import { assertNoHorizontalOverflow, launch } from './support.mjs'

const app = await launch('m3-location-import')
const page = await app.browser.newPage({ viewport: { width: 1280, height: 900 } })
try {
  await app.login(page, 'browser-admin')
  await page.getByText('仅人工录入', { exact: true }).click()
  await page.locator('#hazard-description').fill('M3_TEST_ONLY 楼道堆物影响疏散')
  await page.locator('summary').filter({ hasText: '位置与来源' }).click()
  await page.getByLabel('地址', { exact: true }).fill('幸福路 3 号 2 单元')
  await page.getByLabel('区划', { exact: true }).fill('示例区')
  await page.getByLabel('设施', { exact: true }).fill('居民楼')
  await page.getByLabel('场景', { exact: true }).fill('楼道')
  await page.getByLabel('事件时间', { exact: true }).fill('2026-10-20T09:30')
  await page.getByLabel('数据来源', { exact: true }).selectOption('simulated')
  await page.getByLabel('纬度', { exact: true }).fill('30.123456')
  await page.getByLabel('经度', { exact: true }).fill('120.654321')
  await page.getByLabel('坐标系', { exact: true }).selectOption('gcj02')
  const accepted = page.waitForResponse(r => r.url().endsWith('/api/v1/assessments') && r.request().method() === 'POST')
  await page.getByRole('button', { name: '创建人工记录', exact: true }).click()
  const response = await accepted
  assert.ok([201, 202].includes(response.status()), String(response.status()))
  const payload = await response.json()
  const record = await app.completed(payload.assessment_id || payload.id)
  assert.equal(record.data_source, 'simulated')
  assert.equal(record.address, '幸福路 3 号 2 单元')
  assert.equal(record.location_precision, 'coordinate')
  assert.equal(record.coordinate_source, 'manual')
  assert.equal(record.coordinate_system, 'gcj02')
  assert.ok(record.event_time && record.event_time !== record.created_at)

  const meta = page.locator('.record-meta')
  await meta.getByText('模拟数据', { exact: true }).waitFor()
  await meta.getByText('坐标级', { exact: true }).waitFor()
  await meta.getByText(/手工填写/).waitFor()
  await meta.getByText(/GCJ-02/).waitFor()
  const eventText = await meta.locator('div').filter({ hasText: '事件时间' }).locator('dd').innerText()
  const createdText = await meta.locator('div').filter({ hasText: '录入时间' }).locator('dd').innerText()
  assert.notEqual(eventText, createdText)
  await assertNoHorizontalOverflow(page)
  await page.screenshot({ path: path.join(app.directory, 'manual-location-desktop.png'), fullPage: true, animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  await assertNoHorizontalOverflow(page)
  await page.screenshot({ path: path.join(app.directory, 'manual-location-mobile.png'), fullPage: true, animations: 'disabled' })
  await page.setViewportSize({ width: 1280, height: 900 })

  await page.goto(app.frontendUrl + '/history')
  await page.locator('summary').filter({ hasText: '批量导入案例' }).click()
  const rows = [
    { source_ref: 'M3_TEST_ONLY_BROWSER-1', description: 'M3_TEST_ONLY 公开案例通道堆物',
      data_source: 'public_case', district: '示例区', address: '示例路 9 号',
      latitude: 30.2, longitude: 120.2, coordinate_system: 'wgs84',
      event_time: '2026-10-18T10:00:00+08:00' },
    { source_ref: 'M3_TEST_ONLY_BROWSER-1', description: 'M3_TEST_ONLY 重复行', data_source: 'public_case' },
    { source_ref: 'M3_TEST_ONLY_BAD', description: 'M3_TEST_ONLY 错误来源', data_source: 'guess' },
  ]
  await page.locator('input[aria-label="导入 JSON 文件"]').setInputFiles({
    name: 'm3-import.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(rows)),
  })
  await page.getByRole('button', { name: /导入 3 条/ }).click()
  await page.getByText(/成功 1 条/).waitFor()
  await page.getByText(/重复 1 条/).waitFor()
  await page.getByText(/第 3 行（M3_TEST_ONLY_BAD）/).waitFor()
  const importedRow = page.locator('.el-table__row').filter({ hasText: 'M3_TEST_ONLY 公开案例通道堆物' })
  await importedRow.getByRole('button', { name: '查看', exact: true }).click()
  await page.getByText('导入记录：仅保留位置、来源和时间信息，未做 AI 研判。', { exact: true }).waitFor()
  const importedMeta = page.locator('.record-meta')
  await importedMeta.getByText('公开案例', { exact: true }).waitFor()
  await importedMeta.getByText(/导入$/).waitFor()
  await importedMeta.getByText(/M3_TEST_ONLY_BROWSER-1/).waitFor()
  await assertNoHorizontalOverflow(page)
  await page.screenshot({ path: path.join(app.directory, 'imported-record-desktop.png'), fullPage: true, animations: 'disabled' })

  const repeated = await app.request('POST', '/assessments/import', app.admin, { rows })
  assert.equal(repeated.status, 200)
  const repeatedResult = await repeated.json()
  assert.equal(repeatedResult.imported, 0)
  assert.deepEqual(repeatedResult.duplicates, [1, 2])

  const inspector = await app.browser.newPage({ viewport: { width: 390, height: 844 } })
  await app.login(inspector, 'browser-inspector')
  await inspector.goto(app.frontendUrl + '/history')
  await inspector.getByRole('heading', { name: '历史研判记录', exact: true }).waitFor()
  assert.equal(await inspector.locator('summary').filter({ hasText: '批量导入案例' }).count(), 0)
  await inspector.getByRole('cell', { name: 'M3_TEST_ONLY 公开案例通道堆物' }).waitFor()
  await assertNoHorizontalOverflow(inspector)
  await writeFile(path.join(app.directory, 'result.json'), JSON.stringify({
    passed: true, record: record.id, eventTimeSeparate: true, dataSourceSeparate: true,
    manualAddressWithoutMap: true, importFailuresListed: true, importDuplicatesSkipped: true,
    importedRecordTraceable: true, inspectorCannotImport: true, desktopAndMobile: true,
  }, null, 2))
  console.log(JSON.stringify({ passed: true, directory: app.directory }))
} catch (error) {
  await page.screenshot({ path: path.join(app.directory, 'failure.png'), fullPage: true }).catch(() => {})
  await writeFile(path.join(app.directory, 'failure.txt'), String(error) + '\n' + app.logs())
  throw error
} finally {
  await app.close()
}
