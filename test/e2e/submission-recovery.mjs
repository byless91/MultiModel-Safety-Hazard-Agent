/** Actual browser + Mock backend: lose accepted POST response, reload, recover once. */
import assert from 'node:assert/strict'
import { spawn, execFileSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { createServer } from 'node:net'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root = fileURLToPath(new URL('../../', import.meta.url))
const require = createRequire(new URL('../../frontend/package.json', import.meta.url))
const { chromium } = require('playwright-core')
const reports = path.join(root, 'test/.artifacts/reports')
const python = path.join(root, 'backend/.venv/Scripts/python.exe')
const children = []
let browser

async function port() {
  const server = createServer()
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  const value = server.address().port
  await new Promise((resolve) => server.close(resolve))
  return value
}

function start(executable, args, options = {}) {
  const child = spawn(executable, args, { cwd: root, windowsHide: true, ...options })
  child.logs = ''
  child.stdout.on('data', (data) => { child.logs = (child.logs + data).slice(-12000) })
  child.stderr.on('data', (data) => { child.logs = (child.logs + data).slice(-12000) })
  children.push(child)
  return child
}

async function ready(url, child) {
  const deadline = Date.now() + 30000
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`Test service exited: ${child.logs}`)
    try { if ((await fetch(url)).ok) return } catch { /* service is still starting */ }
    await new Promise((resolve) => setTimeout(resolve, 200))
  }
  throw new Error(`Service did not become ready: ${child.logs}`)
}

try {
  await mkdir(reports, { recursive: true })
  const backendPort = await port()
  const frontendPort = await port()
  const backendUrl = `http://127.0.0.1:${backendPort}`
  const frontendUrl = `http://127.0.0.1:${frontendPort}`
  const stateFile = path.join(reports, 'r4-e2e-server.json')
  const backend = start(python, [path.join(root, 'test/e2e/serve_backend.py'), '--port', String(backendPort),
    '--state-file', stateFile])
  await ready(`${backendUrl}/api/v1/health`, backend)
  const frontend = start(process.execPath, [path.join(root, 'frontend/node_modules/vite/bin/vite.js'),
    '--host', '127.0.0.1', '--port', String(frontendPort), '--strictPort'], {
    cwd: path.join(root, 'frontend'), env: { ...process.env, VITE_API_PROXY: backendUrl },
  })
  await ready(frontendUrl, frontend)
  browser = await chromium.launch({ channel: 'msedge', headless: true })
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  let posts = 0
  let key, assessmentId, jobId, markLost
  const lost = new Promise((resolve) => { markLost = resolve })
  await page.route('**/api/v1/assessments', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    posts += 1
    const response = await route.fetch()
    assert.equal(response.status(), 202)
    const body = await response.json()
    key = route.request().headers()['idempotency-key']
    assessmentId = body.assessment_id
    jobId = body.id
    await route.abort('failed') // Server committed; browser receives no response.
    markLost()
  })
  await page.goto(frontendUrl)
  await page.locator('#hazard-description').fill('小区楼道堆放纸箱杂物，堵塞疏散通道，通行明显受阻')
  await page.getByRole('button', { name: '生成分类建议' }).click()
  await lost
  await page.getByRole('button', { name: '查询本次提交', exact: true }).waitFor()
  assert.match(key, /^submission_[a-f0-9]{32}$/)
  await page.screenshot({ path: path.join(reports, 'r4-submission-recovery.png'), fullPage: true })
  await page.reload()
  assert.equal(await page.evaluate(() => JSON.parse(sessionStorage.getItem('safety_hazard_submission_v1')).key), key)
  await page.getByRole('button', { name: '查询本次提交', exact: true }).click()
  await page.locator('.result-panel').waitFor({ timeout: 30000 })
  assert.equal(posts, 1)
  const items = await (await fetch(`${backendUrl}/api/v1/assessments`)).json()
  assert.equal(items.length, 1)
  assert.equal(items[0].id, assessmentId)
  const finalJob = await (await fetch(`${backendUrl}/api/v1/assessments/${assessmentId}/job`)).json()
  assert.equal(finalJob.id, jobId)
  assert.equal(finalJob.status, 'succeeded')
  const state = JSON.parse(await readFile(stateFile, 'utf8'))
  const database = state.database_url.slice('sqlite:///'.length)
  assert.ok(path.resolve(database).startsWith(path.resolve(root, 'test/.artifacts') + path.sep))
  const counts = JSON.parse(execFileSync(python, ['-c',
    'import json,sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(json.dumps({t:c.execute("SELECT COUNT(*) FROM "+t).fetchone()[0] for t in ["assessments","assessment_jobs","idempotency_keys"]}))',
    database], { encoding: 'utf8', windowsHide: true }))
  assert.deepEqual(counts, { assessments: 1, assessment_jobs: 1, idempotency_keys: 1 })
  await writeFile(path.join(reports, 'r4-e2e.json'), JSON.stringify({
    passed: true, browser: 'Edge headless', provider: 'mock', initial_post_responses_lost: 1,
    create_post_count: posts, reloaded: true, counts, recovered_assessment_id: assessmentId,
    recovered_job_id: jobId, screenshot: 'test/.artifacts/reports/r4-submission-recovery.png',
  }, null, 2) + '\n')
  console.log('R4 browser recovery passed: lost accepted response + page reload; one assessment, one job, one key, one POST')
} finally {
  if (browser) await browser.close()
  for (const child of children.reverse()) child.kill()
}
