/**
 * E2E smoke test for the local MVP.
 * Requires backend on :8001 and frontend dev server on :5173.
 */
import { createRequire } from 'module'

const BASE = process.env.E2E_BASE || 'http://localhost:5173'
const RUNTIME_MODULES =
  process.env.CODEX_NODE_MODULES ||
  'C:/Users/34036/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'

const require = createRequire(RUNTIME_MODULES + '/')
const { chromium } = require('playwright-core')

const browser = await chromium.launch({
  channel: 'msedge',
  headless: true,
})

try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  await page.getByText('现场隐患智能研判').first().waitFor({ timeout: 15000 })

  await page.locator('textarea').first().fill('小区楼道堆放纸箱杂物，堵塞疏散通道，通行明显受阻')
  await page.getByRole('button', { name: /开始研判/ }).click()

  await page.getByText('占用疏散通道').first().waitFor({ timeout: 30000 })
  await page.getByText('参考依据').first().waitFor({ timeout: 10000 })

  const result = await page.locator('.result-title').innerText()
  console.log(JSON.stringify({ status: 'pass', base: BASE, result }))
} finally {
  await browser.close()
}
