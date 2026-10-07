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

  /** Element Plus tab items are stable across versions via this selector. */
  async function openTab(label, scope = page) {
    await scope.locator('.el-tabs__item', { hasText: label }).first().click()
  }

  async function expectText(text, timeout = 15000) {
    await page.getByText(text).first().waitFor({ timeout })
  }

  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  await expectText('现场隐患智能研判')

  await page.locator('textarea').first().fill('小区楼道堆放纸箱杂物，堵塞疏散通道，通行明显受阻')
  await page.getByRole('button', { name: /开始研判/ }).click()
  await expectText('占用疏散通道', 30000)

  const result = await page.locator('.conclusion-title').innerText()

  // Default tab: the operational answer a field worker needs first.
  const actionSections = ['处置建议', '整改工单', '人工复核']
  const checked = []
  for (const section of actionSections) {
    await expectText(section)
    checked.push(section)
  }

  await openTab('证据依据')
  for (const section of ['法规证据', '证据链判定', '证据链', '隐患定位（可选 Bounding Box）']) {
    await expectText(section)
    checked.push(section)
  }

  await openTab('模型分析')
  for (const section of ['风险引擎判定与解释', '模型 A/B 对比', '分歧可视化']) {
    await expectText(section)
    checked.push(section)
  }

  await openTab('整改闭环')
  await expectText('整改回传')
  checked.push('整改回传')

  // Evaluation overview page.
  await page.getByRole('link', { name: '评测总览' }).click()
  await page.waitForURL(/\/evaluation$/, { timeout: 15000 })
  await expectText('评测总览')
  await page.getByRole('button', { name: /刷新/ }).waitFor({ timeout: 15000 })

  const metricLabels = [
    '类别准确率',
    '等级准确率',
    'Severity MAE',
    '±1 容差',
    '证据支持率',
    '无依据结论率',
    '模型分歧率',
    '人工复核率',
    'Unsafe Auto-Pass',
  ]
  for (const label of metricLabels) {
    await page.getByText(label, { exact: true }).first().waitFor({ timeout: 15000 })
  }
  await expectText('Dataset Overview')

  const modeText = await page.locator('.meta-strip').innerText()
  const modeOk = /Mock 模式|真实模型模式/.test(modeText)

  await openTab('消融对比')
  await expectText('消融对比（A-F）')
  for (const column of ['变体', '模式', 'Unsafe']) {
    await page.getByText(column, { exact: true }).first().waitFor({ timeout: 15000 })
  }

  await openTab('错误分析')
  await expectText('失败案例清单')

  console.log(
    JSON.stringify({
      status: 'pass',
      base: BASE,
      result,
      checked_result_sections: checked.length,
      sections: checked,
      checked_evaluation_page: true,
      evaluation_mode_label_ok: modeOk,
    }),
  )
} finally {
  await browser.close()
}
