/** R7/T19: a real paused server worker, real reload/navigation and virtual local wait. */
import assert from 'node:assert/strict'
import path from 'node:path'
import { randomUUID } from 'node:crypto'
import { mkdir, unlink, writeFile } from 'node:fs/promises'
import { launch, root } from './support.mjs'

const gate = path.join(root, 'test/.artifacts/reports', `r7-gate-${randomUUID()}.txt`)
await mkdir(path.dirname(gate), { recursive: true })
await writeFile(gate, 'pause only this disposable test worker')
const app = await launch('r7-async-resume', ['--workflow-gate', gate])
let page
try {
  const context = await app.browser.newContext({ viewport: { width: 1280, height: 900 } })
  page = await context.newPage()
  await app.login(page)
  async function submit(description) {
    const form = new FormData()
    form.append('description', description)
    const response = await app.request('POST', '/assessments', app.admin, form)
    assert.equal(response.status, 202)
    return response.json()
  }
  const first = await submit('出口被纸箱堵住，疏散通道无法通行')
  await page.goto(`${app.frontendUrl}/assessments/${first.assessment_id}`)
  await page.getByRole('heading', { name: /研判进行中|研判正在排队/ }).waitFor()
  await page.reload()
  await page.getByRole('heading', { name: /研判进行中|研判正在排队/ }).waitFor()
  await page.clock.install()
  await page.clock.fastForward(120100)
  await page.getByRole('button', { name: '继续查询', exact: true }).waitFor()
  const serverJob = await (await app.request('GET', `/assessments/${first.assessment_id}/job`, app.admin)).json()
  assert.ok(['running', 'queued'].includes(serverJob.status))
  await page.clock.resume()
  let interrupted = false
  await page.route(`**/assessments/${first.assessment_id}/job`, async (route) => {
    if (!interrupted) { interrupted = true; await route.abort('failed') }
    else await route.continue()
  })
  await page.getByRole('button', { name: '继续查询', exact: true }).click()
  await page.getByText('连接暂时中断，保留当前记录并自动重试查询。').waitFor()
  await unlink(gate)
  await page.locator('.review-form').waitFor({ timeout: 30000 })
  assert.ok(interrupted)
  let pollCalls = 0
  page.on('request', (request) => { if (request.url().includes(`/assessments/${first.assessment_id}/job`)) pollCalls++ })
  await page.waitForTimeout(2300)
  assert.equal(pollCalls, 0)

  await writeFile(gate, 'pause next worker attempt')
  const second = await submit('井盖缺失，行人存在坠落危险')
  await page.goto(`${app.frontendUrl}/assessments/${second.assessment_id}`)
  await page.getByRole('heading', { name: /研判进行中|研判正在排队/ }).waitFor()
  await page.evaluate(async (id) => {
    const { default: router } = await import('/src/router/index.ts')
    await router.push(`/assessments/${id}`)
  }, first.assessment_id)
  await page.locator('.review-form').waitFor()
  assert.ok((await page.locator('.page-subtitle').innerText()).includes('出口'))
  const callsBeforeLeaving = pollCalls
  await page.getByRole('link', { name: '历史记录', exact: true }).first().click()
  await page.waitForTimeout(2300)
  assert.equal(pollCalls, callsBeforeLeaving)
  const failing = await submit('R7_TEST_JOB_FAILURE')
  await unlink(gate)
  await app.completed(second.assessment_id)
  await app.completed(failing.assessment_id)
  await page.goto(`${app.frontendUrl}/assessments/${failing.assessment_id}`)
  await page.getByRole('heading', { name: '研判任务失败', exact: true }).waitFor()
  const failed = await (await app.request('GET', `/assessments/${failing.assessment_id}/job`, app.admin)).json()
  assert.equal(failed.status, 'failed')
  await page.screenshot({ path: path.join(app.directory, 'failed-desktop.png'), fullPage: true })
  await writeFile(path.join(app.directory, 'result.json'), JSON.stringify({ passed: true,
    refreshed_real_running_job: true, virtual_local_wait_ms: 120100, server_kept_running: true,
    temporary_network_failure_recovered: true, terminal_polling_stopped: true,
    reused_route_id_updated: true, left_page_stopped_queries: true, failed_record_visible: true,
    real_model_calls: 0 }, null, 2))
  console.log(`R7 async resume passed: ${app.directory}`)
} catch (error) {
  if (page) await page.screenshot({ path: path.join(app.directory, 'failure.png'), fullPage: true }).catch(() => {})
  await writeFile(path.join(app.directory, 'failure.log'), String(error) + '\n' + app.logs())
  throw error
} finally {
  await unlink(gate).catch(() => {})
  await app.close()
}
