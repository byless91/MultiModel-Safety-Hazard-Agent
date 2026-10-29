/** M2: original knowledge page, version publication and immutable citations. */
import path from 'node:path'
import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'
import { assertNoHorizontalOverflow, launch } from './support.mjs'

const app = await launch('m2-knowledge')
const page = await app.browser.newPage({ viewport: { width: 1280, height: 900 } })
try {
  await app.login(page, 'browser-admin')
  await page.goto(app.frontendUrl + '/knowledge')
  await page.getByRole('heading', { name: '知识库管理', exact: true }).waitFor()
  if (process.argv.includes('--before')) {
    await assertNoHorizontalOverflow(page)
    await page.screenshot({ path: path.join(app.directory, 'before-desktop.png'), fullPage: true, animations: 'disabled' })
    await page.setViewportSize({ width: 390, height: 844 })
    await assertNoHorizontalOverflow(page)
    await page.screenshot({ path: path.join(app.directory, 'before-mobile.png'), fullPage: true, animations: 'disabled' })
    console.log(JSON.stringify({ before: true, directory: app.directory }))
  } else {
    const title = 'M2_TEST_ONLY_版本验证资料'
    const content = '第一条 M2_TEST_ONLY 测试条款：疏散通道应保持畅通。'
    await page.getByLabel('行业目录', { exact: true }).selectOption('fire')
    await page.getByLabel('条款关键词', { exact: true }).fill('疏散通道')
    await page.getByRole('button', { name: '检索已审核条款', exact: true }).click()
    await page.getByText('未找到已审核的有效条款，请核对行业或补充资料', { exact: true }).waitFor()
    await page.locator('summary').filter({ hasText: '上传知识文档' }).click()
    await page.getByLabel('文档标题', { exact: true }).fill(title)
    await page.getByLabel('原始来源链接', { exact: true }).fill('https://example.test/m2-engineering-only')
    await page.getByLabel('版本标识', { exact: true }).fill('v1')
    await page.getByLabel('文档行业', { exact: true }).selectOption('fire')
    await page.getByLabel('适用范围', { exact: true }).fill('仅限工程测试的消防场景，非真实法规资料')
    async function upload(text, name) {
      await page.locator('.doc-form input[type=file]').setInputFiles({ name, mimeType: 'text/plain', buffer: Buffer.from(text) })
      const pending = page.waitForResponse(r => r.url().endsWith('/knowledge/documents') && r.request().method() === 'POST')
      await page.getByRole('button', { name: '保存待审核版本', exact: true }).click()
      const response = await pending
      assert.equal(response.status(), 201)
      return response.json()
    }
    const first = await upload(content, 'm2-v1.txt')
    assert.equal(first.review_status, 'unreviewed')
    async function currentSearch(industry = 'fire') {
      const response = await app.request('GET', `/knowledge/search?query=${encodeURIComponent('疏散通道')}&industry=${industry}`, app.admin)
      assert.equal(response.status, 200)
      return response.json()
    }
    assert.equal((await currentSearch()).items.length, 0)
    let approvals = 0
    page.on('request', r => { if (r.url().endsWith(`/${first.id}/review`) && r.method() === 'POST') approvals++ })
    async function approve() {
      await page.getByLabel('审核意见', { exact: true }).fill('人工核对工程测试原文、版本及范围，仅验证发布链路')
      await page.getByLabel('已核对原始来源、版本、条款原文和适用范围', { exact: true }).check()
      await page.locator('.review-form').evaluate(form => { form.requestSubmit(); form.requestSubmit() })
      await page.getByRole('button', { name: '停用此版本', exact: true }).waitFor()
    }
    await approve()
    assert.equal(approvals, 1)
    let rows = (await currentSearch()).items
    assert.equal(rows[0].document_id, first.id)
    assert.equal(rows[0].review_status_at_retrieval, 'approved')
    const form = new FormData()
    form.append('description', '疏散通道被纸箱堆物堵塞')
    form.append('mode', 'classification')
    const accepted = await app.request('POST', '/assessments', app.admin, form)
    assert.equal(accepted.status, 202)
    const job = await accepted.json()
    const record = await app.completed(job.assessment_id)
    assert.equal(record.evidence[0].document_id, first.id)
    const beforeEvidence = record.evidence

    await page.getByRole('button', { name: '上传此文档的新版本', exact: true }).click()
    await page.getByLabel('版本标识', { exact: true }).fill('v2')
    assert.equal(await page.getByLabel('文档行业', { exact: true }).isDisabled(), true)
    const second = await upload(content + '\n第二条 第二版工程测试，需现场核实。', 'm2-v2.txt')
    assert.equal(second.series_id, first.series_id)
    assert.equal(second.supersedes_id, first.id)
    assert.notEqual(second.content_sha256, first.content_sha256)
    assert.equal((await currentSearch()).items[0].version, 'v1')
    await approve()
    rows = (await currentSearch()).items
    assert.equal(rows[0].version, 'v2')
    const old = await (await app.request('GET', `/knowledge/documents/${first.id}`, app.admin)).json()
    assert.equal(old.review_status, 'superseded')
    assert.equal(old.content_sha256, first.content_sha256)
    assert.equal(old.content, content)
    const saved = await (await app.request('GET', `/assessments/${record.id}`, app.admin)).json()
    assert.deepEqual(saved.evidence, beforeEvidence)
    const exported = await (await app.request('GET', `/assessments/${record.id}/export`, app.admin)).json()
    assert.ok(exported.content.includes(first.content_sha256))
    const oldRow = page.locator('.el-table__row').filter({ hasText: 'v1' })
    await oldRow.getByRole('button', { name: '查看版本', exact: true }).click()
    await page.locator('.detail-card').getByRole('heading', { name: title + ' · v1', exact: true }).waitFor()
    await page.getByText('已被新版本替代', { exact: true }).last().waitFor()
    await page.evaluate(() => window.scrollTo(0, 0))
    await assertNoHorizontalOverflow(page)
    await page.screenshot({ path: path.join(app.directory, 'versions-desktop.png'), fullPage: true, animations: 'disabled' })
    await page.setViewportSize({ width: 390, height: 844 })
    await assertNoHorizontalOverflow(page)
    await page.screenshot({ path: path.join(app.directory, 'versions-mobile.png'), fullPage: true, animations: 'disabled' })

    for (const industry of ['production', 'community', 'forest']) {
      const file = new FormData()
      file.append('title', `M2_TEST_ONLY_${industry}`)
      file.append('source', 'https://example.test/m2-engineering-only')
      file.append('version', 'v1')
      file.append('industry', industry)
      file.append('applicability', '仅工程测试场景')
      file.append('file', new Blob(['第一条 工程测试：疏散通道资料。'], { type: 'text/plain' }), `${industry}.txt`)
      const result = await app.request('POST', '/knowledge/documents', app.admin, file)
      assert.equal(result.status, 201)
      const document = await result.json()
      const approval = await app.request('POST', `/knowledge/documents/${document.id}/review`, app.admin,
        { decision: 'approve', note: '仅工程测试审核', revision: 0, source_checked: true })
      assert.equal(approval.status, 200)
      assert.ok((await currentSearch(industry)).items.every(row => row.industry === industry))
    }
    const inspector = await app.browser.newPage({ viewport: { width: 390, height: 844 } })
    await app.login(inspector, 'browser-inspector')
    await inspector.goto(app.frontendUrl + '/knowledge')
    await inspector.getByText('当前账号可查询和核对资料；上传、审核和停用由管理员处理。').waitFor()
    assert.equal(await inspector.locator('.upload-card').count(), 0)
    await inspector.getByLabel('行业目录', { exact: true }).selectOption('fire')
    await inspector.getByLabel('条款关键词', { exact: true }).fill('疏散通道')
    await inspector.getByRole('button', { name: '检索已审核条款', exact: true }).click()
    await inspector.getByRole('button', { name: '查看引用版本', exact: true }).first().waitFor()
    assert.equal(await inspector.locator('.review-form').count(), 0)
    await assertNoHorizontalOverflow(inspector)
    await page.setViewportSize({ width: 1280, height: 900 })
    await page.locator('.el-table__row').filter({ hasText: 'v2' }).getByRole('button', { name: '查看版本', exact: true }).click()
    await page.getByLabel('审核意见', { exact: true }).fill('工程测试停用，旧引用须保留')
    await page.getByRole('button', { name: '停用此版本', exact: true }).click()
    await page.locator('.detail-card').getByText('已停用', { exact: true }).waitFor()
    assert.equal((await currentSearch()).items.length, 0)
    await writeFile(path.join(app.directory, 'result.json'), JSON.stringify({ passed: true, first: first.id, second: second.id,
      industryDirectories: true, approvalRequired: true, duplicateApprovalBlocked: true, oldCitationsImmutable: true,
      inspectorReadOnly: true, retirementVerified: true, desktopAndMobile: true, liveLegalQualityEvaluated: false }, null, 2))
    console.log(JSON.stringify({ passed: true, directory: app.directory }))
  }
} catch (error) {
  await page.screenshot({ path: path.join(app.directory, 'failure.png'), fullPage: true }).catch(() => {})
  await writeFile(path.join(app.directory, 'failure.txt'), String(error) + '\n' + app.logs())
  throw error
} finally {
  await app.close()
}
