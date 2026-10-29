/** M6: two isolated deployments, verified pack export/import, citation preservation and offline use. */
import path from 'node:path'
import assert from 'node:assert/strict'
import { readFile, writeFile } from 'node:fs/promises'
import { assertNoHorizontalOverflow, launch } from './support.mjs'

const cloud = await launch('m6-cloud')
const local = await launch('m6-local')
const page = await local.browser.newPage({ viewport: { width: 1280, height: 900 }, acceptDownloads: true })
const title = 'M6_TEST_ONLY 云端审核规范'

async function upload(app, { version, body, parent }) {
  const form = new FormData()
  form.append('title', title)
  form.append('source', 'https://example.test/m6-authority')
  form.append('version', version)
  form.append('industry', 'fire')
  form.append('applicability', 'M6_TEST_ONLY 消防场景')
  if (parent) form.append('supersedes_id', parent.id)
  form.append('file', new Blob([body], { type: 'text/plain' }), `${version}.txt`)
  const response = await app.request('POST', '/knowledge/documents', app.admin, form)
  if (response.status !== 201) throw new Error(await response.text())
  return response.json()
}

async function approve(app, doc) {
  const response = await app.request('POST', `/knowledge/documents/${doc.id}/review`, app.admin, {
    decision: 'approve', revision: doc.revision, source_checked: true,
    note: 'M6_TEST_ONLY 云端人工审核',
  })
  if (response.status !== 200) throw new Error(await response.text())
  return response.json()
}

async function exportPack(app) {
  const response = await app.request('GET', '/knowledge/pack/export', app.admin)
  if (response.status !== 200) throw new Error(await response.text())
  return response.json()
}

async function importPackViaUi(pack) {
  await page.locator('input[aria-label="导入知识包文件"]').setInputFiles({
    name: `pack-${pack.pack_version}.json`, mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify(pack)),
  })
  await page.getByText(new RegExp(`批次 ${pack.pack_version}`)).waitFor()
}

try {
  const v1 = await approve(cloud, await upload(cloud, {
    version: 'v1', body: '第一条 M6 云端条款：疏散通道应保持畅通。',
  }))
  const packV1 = await exportPack(cloud)
  assert.equal(packV1.documents.length, 1)
  assert.equal(packV1.documents[0].version, 'v1')
  assert.equal(packV1.documents[0].review_status, 'approved')

  await local.login(page, 'browser-admin')
  await page.goto(local.frontendUrl + '/knowledge')
  await page.getByRole('heading', { name: '知识包同步', exact: true }).waitFor()
  await importPackViaUi(packV1)
  await page.getByText(new RegExp(`本地知识包版本：${packV1.pack_version}`)).waitFor()
  await page.getByText('最后同步', { exact: false }).waitFor()
  await page.getByLabel('行业目录', { exact: true }).selectOption('fire')
  await page.getByLabel('条款关键词', { exact: true }).fill('疏散通道')
  await page.getByRole('button', { name: '检索已审核条款', exact: true }).click()
  const firstResult = page.locator('.search-results li').first()
  await firstResult.waitFor()
  assert.ok((await firstResult.innerText()).includes('v1'))
  const localSearchV1 = await (await local.request(
    'GET', '/knowledge/search?query=%E7%96%8F%E6%95%A3%E9%80%9A%E9%81%93&industry=fire', local.admin)).json()
  assert.equal(localSearchV1.items[0].version, 'v1')
  const localV1Id = localSearchV1.items[0].document_id

  const accepted = await local.request('POST', '/assessments', local.admin, (() => {
    const form = new FormData()
    form.append('description', '疏散通道被纸箱堵塞')
    form.append('mode', 'classification')
    return form
  })())
  assert.equal(accepted.status, 202)
  const job = await accepted.json()
  const record = await local.completed(job.assessment_id)
  assert.equal(record.evidence[0].document_id, localV1Id)
  const oldEvidence = record.evidence

  const v2 = await approve(cloud, await upload(cloud, {
    version: 'v2', parent: v1,
    body: '第一条 M6 云端条款第二版：疏散通道应保持畅通，并定期复核。',
  }))
  const packV2 = await exportPack(cloud)
  assert.equal(packV2.documents.length, 1)
  assert.equal(packV2.documents[0].version, 'v2')
  await importPackViaUi(packV2)
  await page.getByText(new RegExp(`本地知识包版本：${packV2.pack_version}`)).waitFor()
  await page.getByText(/替代 1/).waitFor()
  const saved = await (await local.request('GET', `/assessments/${record.id}`, local.admin)).json()
  assert.deepEqual(saved.evidence, oldEvidence)
  assert.equal(saved.evidence[0].version, 'v1')
  const oldDoc = await (await local.request('GET', `/knowledge/documents/${localV1Id}`, local.admin)).json()
  assert.equal(oldDoc.review_status, 'superseded')
  assert.equal(oldDoc.content, '第一条 M6 云端条款：疏散通道应保持畅通。')
  const upgraded = await (await local.request(
    'GET', '/knowledge/search?query=%E7%96%8F%E6%95%A3%E9%80%9A%E9%81%93&industry=fire', local.admin)).json()
  assert.equal(upgraded.items[0].version, 'v2')

  const downloadEvent = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出知识包', exact: true }).click()
  const download = await downloadEvent
  const exportedPath = path.join(local.directory, 'local-pack.json')
  await download.saveAs(exportedPath)
  const exported = JSON.parse(await readFile(exportedPath, 'utf8'))
  assert.equal(exported.format, 'safety-knowledge-pack-v1')
  assert.equal(exported.documents[0].version, 'v2')

  const tampered = structuredClone(packV2)
  tampered.documents[0].content_text = '被篡改的条款'
  await page.locator('input[aria-label="导入知识包文件"]').setInputFiles({
    name: 'tampered.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(tampered)),
  })
  await page.getByText(/知识包校验失败/).waitFor()
  const afterTamper = await (await local.request('GET', '/knowledge/pack/status', local.admin)).json()
  assert.equal(afterTamper.last_sync.pack_version, packV2.pack_version)

  const blocked = new Set()
  await page.route('**/*', route => {
    const url = new URL(route.request().url())
    if (['127.0.0.1', 'localhost'].includes(url.hostname)) return route.continue()
    blocked.add(url.hostname)
    return route.abort()
  })
  await page.goto(local.frontendUrl + '/')
  await page.getByText('仅人工录入', { exact: true }).click()
  await page.locator('#hazard-description').fill('M6_TEST_ONLY 断网人工录入：楼道堆物')
  const manualAccepted = page.waitForResponse(r => r.url().endsWith('/api/v1/assessments') && r.request().method() === 'POST')
  await page.getByRole('button', { name: '创建人工记录', exact: true }).click()
  const manualResponse = await manualAccepted
  assert.ok([201, 202].includes(manualResponse.status()))
  await page.locator('.result-panel, .record-meta').first().waitFor({ timeout: 30000 })
  await page.goto(local.frontendUrl + '/knowledge')
  await page.getByLabel('条款关键词', { exact: true }).fill('疏散通道')
  await page.getByRole('button', { name: '检索已审核条款', exact: true }).click()
  await page.locator('.search-results li').first().waitFor()
  await page.goto(local.frontendUrl + '/history')
  await page.getByRole('cell', { name: 'M6_TEST_ONLY 断网人工录入：楼道堆物' }).waitFor()
  await assertNoHorizontalOverflow(page)
  await page.screenshot({ path: path.join(local.directory, 'offline-local.png'), fullPage: true, animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  await assertNoHorizontalOverflow(page)

  const finalStatus = await (await local.request('GET', '/knowledge/pack/status', local.admin)).json()
  assert.equal(finalStatus.last_sync.pack_version, packV2.pack_version)
  await writeFile(path.join(local.directory, 'result.json'), JSON.stringify({
    passed: true, cloudPackV1: packV1.pack_version, cloudPackV2: packV2.pack_version,
    localSync: finalStatus.last_sync.pack_version, importedV1: true, importedV2: true,
    citationPreserved: true, oldContentPreserved: true, searchUpgraded: true,
    tamperedRejected: true, exportDownloaded: true, offlineManualEntry: true,
    offlineKnowledgeSearch: true, offlineHistory: true, blockedHosts: [...blocked],
    desktopAndMobile: true,
  }, null, 2))
  console.log(JSON.stringify({ passed: true, directory: local.directory }))
} catch (error) {
  await page.screenshot({ path: path.join(local.directory, 'failure.png'), fullPage: true }).catch(() => {})
  await writeFile(path.join(local.directory, 'failure.txt'),
    `${error}\n--- local ---\n${local.logs()}\n--- cloud ---\n${cloud.logs()}`)
  throw error
} finally {
  await page.close().catch(() => undefined)
  await local.close()
  await cloud.close()
}
