/** Real Edge + disposable Mock APIs: none, static credential, JWT and no static 401 loop. */
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { createRequire } from 'node:module'
import { createServer } from 'node:net'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root = fileURLToPath(new URL('../../', import.meta.url))
const require = createRequire(new URL('../../frontend/package.json', import.meta.url))
const { chromium } = require('playwright-core')
const reports = path.join(root, 'test/.artifacts/reports')
const children = []
let browser

async function freePort() {
  const server = createServer()
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  const value = server.address().port
  await new Promise((resolve) => server.close(resolve))
  return value
}

function start(executable, args, cwd = root) {
  const child = spawn(executable, args, { cwd, windowsHide: true })
  child.logs = ''
  child.stdout.on('data', (data) => { child.logs = (child.logs + data).slice(-8000) })
  child.stderr.on('data', (data) => { child.logs = (child.logs + data).slice(-8000) })
  children.push(child)
  return child
}

async function ready(url, child) {
  for (let i = 0; i < 150; i++) {
    if (child.exitCode !== null) throw new Error(child.logs)
    try { if ((await fetch(url)).ok) return } catch { /* starting */ }
    await new Promise((resolve) => setTimeout(resolve, 200))
  }
  throw new Error(`Service startup failed: ${child.logs}`)
}

try {
  await mkdir(reports, { recursive: true })
  const frontendPort = await freePort()
  const frontendUrl = `http://127.0.0.1:${frontendPort}`
  const frontend = start(process.execPath, [path.join(root, 'frontend/node_modules/vite/bin/vite.js'),
    '--host', '127.0.0.1', '--port', String(frontendPort), '--strictPort'], path.join(root, 'frontend'))
  await ready(frontendUrl, frontend)
  browser = await chromium.launch({ channel: 'msedge', headless: true })
  const results = []
  for (const mode of ['none', 'token', 'jwt']) {
    const port = await freePort()
    const backendUrl = `http://127.0.0.1:${port}`
    const backend = start(path.join(root, 'backend/.venv/Scripts/python.exe'),
      [path.join(root, 'test/e2e/serve_backend.py'), '--port', String(port), '--auth-mode', mode,
        '--state-file', path.join(reports, `r5-auth-server-${mode}.json`)])
    await ready(`${backendUrl}/api/v1/health`, backend)
    const context = await browser.newContext({ viewport: { width: 1200, height: 850 } })
    const page = await context.newPage()
    const requests = []
    await page.route('**/api/v1/**', async (route) => {
      const url = new URL(route.request().url())
      requests.push(url.pathname)
      const response = await route.fetch({ url: backendUrl + url.pathname + url.search })
      await route.fulfill({ response })
    })
    await page.goto(`${frontendUrl}/login`)
    if (mode === 'none') {
      await page.getByText('当前为本地演示模式，无需登录。此模式没有访问保护。').waitFor()
      assert.equal(await page.locator('input').count(), 0)
      await page.getByRole('button', { name: '返回工作台' }).click()
    } else if (mode === 'token') {
      await page.getByPlaceholder('请输入运维提供的静态凭证').waitFor()
      assert.equal(await page.getByPlaceholder('请输入用户名').count(), 0)
      await page.screenshot({ path: path.join(reports, 'r5-auth-token.png'), fullPage: true })
      await page.getByPlaceholder('请输入运维提供的静态凭证').fill('bad-candidate')
      await page.getByRole('button', { name: '验证凭证', exact: true }).click()
      await page.getByText('未授权', { exact: true }).waitFor()
      await page.getByPlaceholder('请输入运维提供的静态凭证').fill('r5-browser-static-credential')
      await page.getByRole('button', { name: '验证凭证', exact: true }).click()
    } else {
      await page.getByPlaceholder('请输入用户名').fill('browser-admin')
      await page.getByPlaceholder('请输入密码').fill('browser-pass-123')
      await page.getByRole('button', { name: '登 录' }).click()
    }
    await page.waitForURL(`${frontendUrl}/`)
    await page.getByRole('button', { name: '开始研判' }).waitFor()
    if (mode === 'token') {
      await page.evaluate(async () => {
        const { api } = await import('/src/api/client.ts')
        await api.get('/health')
        await api.get('/auth/check', { headers: { Authorization: 'Bearer bad-candidate' } }).catch(() => undefined)
      })
      assert.equal(await page.evaluate(() => localStorage.getItem('safety_hazard_token')), 'r5-browser-static-credential')
      assert.equal(page.url(), `${frontendUrl}/`)
      assert.equal(requests.filter((url) => url.endsWith('/auth/token') || url.endsWith('/auth/me')).length, 0)
    }
    if (mode === 'jwt') {
      await page.reload()
      await page.getByRole('button', { name: '开始研判' }).waitFor()
      assert.ok(requests.some((url) => url.endsWith('/auth/me')))
      assert.equal(page.url(), `${frontendUrl}/`)
    }
    results.push({ mode, passed: true, requests: requests.length })
    await context.close()
    backend.kill()
    console.log(`R5 browser ${mode} passed`)
  }
  await writeFile(path.join(reports, 'r5-auth-browser.json'), JSON.stringify({ passed: true, results,
    static_401_preserves_credential: true, no_static_password_login_or_user_probe: true, jwt_reload: true }, null, 2) + '\n')
} finally {
  if (browser) await browser.close()
  for (const child of children.reverse()) child.kill()
}
