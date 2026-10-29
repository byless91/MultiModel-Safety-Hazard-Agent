/** M4: confirmed-record distributions, trend, map and rectification benchmarks. */
import path from 'node:path'
import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import { assertNoHorizontalOverflow, launch } from './support.mjs'

const app = await launch('m4-analytics')
const page = await app.browser.newPage({ viewport: { width: 1280, height: 900 } })

async function seed({ description, district, facility, scene, eventTime, latitude, longitude,
  coordinateSystem, category, riskLevel, rectificationNote, confirm = true }) {
  const form = new FormData()
  form.append('description', description)
  form.append('mode', 'manual')
  form.append('district', district)
  form.append('facility', facility)
  form.append('scene', scene)
  form.append('event_time', eventTime)
  form.append('data_source', 'report')
  if (latitude !== undefined) {
    form.append('latitude', String(latitude))
    form.append('longitude', String(longitude))
    form.append('coordinate_system', coordinateSystem)
  }
  const response = await app.request('POST', '/assessments', app.admin, form)
  if (![201, 202].includes(response.status)) throw new Error(await response.text())
  const payload = await response.json()
  const id = payload.assessment_id || payload.id
  await app.completed(id)
  if (category) {
    const saved = await app.request('POST', `/assessments/${id}/classification`, app.admin, {
      category, tags: [], risk_level: riskLevel, note: 'M4_TEST_ONLY 人工核实',
      taxonomy_version: 'm1-v1', revision: 0,
    })
    assert.equal(saved.status, 200)
    if (confirm) {
      const confirmed = await app.request('POST', `/assessments/${id}/confirm`, app.admin,
        { confirmed: true, edits: {} })
      assert.equal(confirmed.status, 200)
    }
  }
  if (rectificationNote) {
    const rectified = await app.request('POST', `/assessments/${id}/rectification/confirm`, app.admin,
      { resolved: false, note: rectificationNote })
    assert.equal(rectified.status, 200)
  }
  return id
}

try {
  const both = await seed({
    description: 'M4_TEST_ONLY 居民楼楼道疏散通道堆物', district: '甲区', facility: '居民楼', scene: '楼道',
    eventTime: '2026-01-10T09:00:00+08:00', latitude: 30.2, longitude: 120.2,
    coordinateSystem: 'gcj02', category: '占用疏散通道', riskLevel: 1,
  })
  const ungraded = await seed({
    description: 'M4_TEST_ONLY 居民楼楼道灭火器过期', district: '乙区', facility: '居民楼', scene: '楼道',
    eventTime: '2026-03-10T09:00:00+08:00', latitude: 30.3, longitude: 120.3,
    coordinateSystem: 'wgs84', category: '消防器材失效', riskLevel: null,
    rectificationNote: '已更换灭火器并复检',
  })
  await seed({
    description: 'M4_TEST_ONLY 市场通道堆物', district: '甲区', facility: '市场', scene: '楼道',
    eventTime: '2026-03-20T09:00:00+08:00', category: '占用疏散通道', riskLevel: 3,
    rectificationNote: '已安排清理并设置警示',
  })
  await seed({
    description: 'M4_TEST_ONLY 未确认记录', district: '甲区', facility: '居民楼', scene: '楼道',
    eventTime: '2026-02-01T09:00:00+08:00',
  })
  const imported = await app.request('POST', '/assessments/import', app.admin, { rows: [{
    source_ref: 'M4_TEST_ONLY_PUBLIC-1', description: 'M4_TEST_ONLY 公开案例',
    data_source: 'public_case', event_time: '2026-02-05T00:00:00+08:00',
  }] })
  assert.equal(imported.status, 200)

  await app.login(page, 'browser-admin')
  await page.goto(app.frontendUrl + '/analytics')
  await page.getByRole('heading', { name: '管理分析', exact: true }).waitFor()
  const totalCell = page.locator('.summary-cell').filter({ hasText: '已确认记录' })
  await totalCell.getByText('3', { exact: true }).waitFor()
  const ungradedCell = page.locator('.summary-cell').filter({ hasText: '未分级' })
  await ungradedCell.getByText('1', { exact: true }).waitFor()
  const collectedCell = page.locator('.summary-cell').filter({ hasText: '收集到的公开案例' })
  await collectedCell.getByText('1', { exact: true }).waitFor()
  const february = page.locator('.month-list li').filter({ hasText: '2026-02' })
  await february.getByText('0 条', { exact: true }).waitFor()
  await page.locator('.map-canvas path.leaflet-interactive').first().waitFor({ timeout: 15000 })
  assert.equal(await page.locator('.map-canvas path.leaflet-interactive').count(), 2)
  assert.equal(await page.locator('.point-list a').count(), 2)
  await assertNoHorizontalOverflow(page)
  await page.screenshot({ path: path.join(app.directory, 'analytics-desktop.png'), fullPage: true, animations: 'disabled' })

  await page.locator('.point-list a').first().click()
  await page.getByRole('heading', { name: '分类记录详情', exact: true }).waitFor()
  await page.goto(app.frontendUrl + '/analytics')
  await page.getByRole('heading', { name: '管理分析', exact: true }).waitFor()

  await page.getByLabel('对标设施', { exact: true }).selectOption('居民楼')
  await page.getByLabel('对标场景', { exact: true }).selectOption('楼道')
  await page.getByRole('button', { name: '查询对标', exact: true }).click()
  await page.getByText('样本量 2 条', { exact: true }).waitFor()
  await page.getByText('来源：现场上报 2 条', { exact: true }).waitFor()
  const benchmarkRows = page.locator('.benchmark-table tbody tr')
  assert.equal(await benchmarkRows.count(), 2)
  await benchmarkRows.first().getByText('设施与场景一致', { exact: true }).waitFor()
  const firstBenchmark = benchmarkRows.first()
  assert.ok((await firstBenchmark.innerText()).includes('乙区'))
  await firstBenchmark.getByRole('link', { name: '查看', exact: true }).click()
  await page.getByText('M4_TEST_ONLY 居民楼楼道灭火器过期', { exact: true }).waitFor()
  assert.equal(page.url(), `${app.frontendUrl}/assessments/${ungraded}`)

  await page.goto(app.frontendUrl + '/analytics')
  await page.getByLabel('对标设施', { exact: true }).selectOption('居民楼')
  await page.getByLabel('对标场景', { exact: true }).selectOption('楼道')
  await page.getByRole('button', { name: '查询对标', exact: true }).click()
  await page.getByText('样本量 2 条', { exact: true }).waitFor()

  const later = await seed({
    description: 'M4_TEST_ONLY 页面打开后确认的记录', district: '甲区', facility: '居民楼', scene: '楼道',
    eventTime: '2026-04-05T09:00:00+08:00', category: '占用疏散通道', riskLevel: 2, confirm: false,
  })
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await totalCell.getByText('3', { exact: true }).waitFor()
  const confirmedLater = await app.request('POST', `/assessments/${later}/confirm`, app.admin,
    { confirmed: true, edits: {} })
  assert.equal(confirmedLater.status, 200)
  await page.getByRole('button', { name: '刷新', exact: true }).click()
  await totalCell.getByText('4', { exact: true }).waitFor()

  await page.setViewportSize({ width: 390, height: 844 })
  await assertNoHorizontalOverflow(page)
  await page.screenshot({ path: path.join(app.directory, 'analytics-mobile.png'), fullPage: true, animations: 'disabled' })

  const inspector = await app.browser.newPage({ viewport: { width: 1280, height: 900 } })
  await app.login(inspector, 'browser-inspector')
  assert.equal(await inspector.getByRole('link', { name: '管理分析', exact: true }).count(), 0)
  await inspector.goto(app.frontendUrl + '/analytics')
  await inspector.getByText('需要角色：reviewer/admin', { exact: false }).waitFor()
  assert.equal(await inspector.locator('.summary-grid').count(), 0)

  await writeFile(path.join(app.directory, 'result.json'), JSON.stringify({
    passed: true, both, ungraded, eventTimeMonths: true, zeroMonth: true, ungradedShown: true,
    mapPoints: 2, benchmarkSample: 2, benchmarkSources: true, drillDown: true,
    unconfirmedExcluded: true, liveUpdate: true, collected: true, inspectorBlocked: true,
    desktopAndMobile: true,
  }, null, 2))
  console.log(JSON.stringify({ passed: true, directory: app.directory }))
} catch (error) {
  await page.screenshot({ path: path.join(app.directory, 'failure.png'), fullPage: true }).catch(() => {})
  await writeFile(path.join(app.directory, 'failure.txt'), String(error) + '\n' + app.logs())
  throw error
} finally {
  await app.close()
}
