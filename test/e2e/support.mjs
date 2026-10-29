/** Disposable real browser / Mock API harness. Never targets an existing user service. */
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { createRequire } from 'node:module'
import { createServer } from 'node:net'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { randomUUID } from 'node:crypto'

export const root = fileURLToPath(new URL('../../', import.meta.url))
const require = createRequire(new URL('../../frontend/package.json', import.meta.url))
const { chromium } = require('playwright-core')

async function freePort() {
  const server = createServer()
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  const value = server.address().port
  await new Promise((resolve) => server.close(resolve))
  return value
}

export async function launch(name, backendArguments = []) {
  const directory = path.join(root, 'test/.artifacts/reports', `${name}-${randomUUID()}`)
  await mkdir(directory, { recursive: true })
  const children = []
  let browser
  function start(executable, args, cwd = root, env = process.env) {
    const child = spawn(executable, args, { cwd, env, windowsHide: true })
    child.logs = ''
    child.stdout.on('data', (data) => { child.logs = (child.logs + data).slice(-12000) })
    child.stderr.on('data', (data) => { child.logs = (child.logs + data).slice(-12000) })
    children.push(child)
    return child
  }
  async function ready(url, child) {
    const deadline = Date.now() + 30000
    while (Date.now() < deadline) {
      if (child.exitCode !== null) throw new Error(child.logs)
      try { if ((await fetch(url)).ok) return } catch { /* booting */ }
      await new Promise((resolve) => setTimeout(resolve, 200))
    }
    throw new Error(`Service did not become ready: ${child.logs}`)
  }
  async function close() {
    if (browser) await browser.close()
    for (const child of children.reverse()) child.kill()
  }
  try {
    const backendUrl = `http://127.0.0.1:${await freePort()}`
    const frontendUrl = `http://127.0.0.1:${await freePort()}`
    const backend = start(process.env.PYTHON || path.join(root, process.platform === 'win32'
      ? 'backend/.venv/Scripts/python.exe' : 'backend/.venv/bin/python'),
    [path.join(root, 'test/e2e/serve_backend.py'), '--port', new URL(backendUrl).port,
      '--auth-mode', 'jwt', '--state-file', path.join(directory, 'server.json'), ...backendArguments])
    await ready(`${backendUrl}/api/v1/ready`, backend)
    const frontend = start(process.execPath, [path.join(root, 'frontend/node_modules/vite/bin/vite.js'),
      '--host', '127.0.0.1', '--port', new URL(frontendUrl).port, '--strictPort'],
    path.join(root, 'frontend'), { ...process.env, VITE_API_PROXY: backendUrl })
    await ready(frontendUrl, frontend)
    browser = await chromium.launch({ ...(process.platform === 'win32' ? { channel: 'msedge' } : {}), headless: true })
    async function request(method, route, token, body) {
      const headers = token ? { Authorization: `Bearer ${token}` } : {}
      if (body && !(body instanceof FormData) && !(body instanceof URLSearchParams)) {
        headers['Content-Type'] = 'application/json'
        body = JSON.stringify(body)
      }
      return fetch(backendUrl + '/api/v1' + route, { method, headers, body })
    }
    async function token(username, password = 'browser-pass-123') {
      const response = await request('POST', '/auth/token', null, new URLSearchParams({ username, password }))
      assert.equal(response.status, 200)
      return (await response.json()).access_token
    }
    const admin = await token('browser-admin')
    for (const role of ['reviewer', 'inspector']) {
      const response = await request('POST', '/admin/users', admin, {
        username: `browser-${role}`, password: 'browser-pass-123', role,
      })
      assert.equal(response.status, 201, await response.text())
    }
    async function login(page, username = 'browser-admin') {
      await page.goto(frontendUrl + '/login')
      await page.getByPlaceholder('请输入用户名').fill(username)
      await page.getByPlaceholder('请输入密码').fill('browser-pass-123')
      await page.getByRole('button', { name: '登 录' }).click()
      await page.waitForURL(frontendUrl + '/')
    }
    async function completed(id) {
      for (let i = 0; i < 150; i++) {
        const response = await request('GET', `/assessments/${id}`, admin)
        const item = await response.json()
        if (item.status !== 'pending') return item
        await new Promise((resolve) => setTimeout(resolve, 100))
      }
      throw new Error('Disposable assessment did not complete')
    }
    async function create(description = '安全出口被纸箱货物堵塞，疏散通道无法通行') {
      const form = new FormData()
      form.append('description', description)
      const response = await request('POST', '/assessments', admin, form)
      assert.equal(response.status, 202)
      const job = await response.json()
      return completed(job.assessment_id)
    }
    return { browser, directory, backendUrl, frontendUrl, request, token, admin, login, completed, create, close,
      logs: () => children.map((child) => child.logs).join('\n') }
  } catch (error) {
    await close()
    throw error
  }
}
