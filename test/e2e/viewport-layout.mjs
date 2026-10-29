/** R8: transient resize layout may settle; genuine overflow must fail. */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { assertNoHorizontalOverflow, root } from './support.mjs'

const require = createRequire(new URL('../../frontend/package.json', import.meta.url))
const { chromium } = require('playwright-core')
const browser = await chromium.launch({ ...(process.platform === 'win32' ? { channel: 'msedge' } : {}), headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
  await page.setContent('<style>body { margin: 0 }</style><div style="width:100%">fits</div>')
  await assertNoHorizontalOverflow(page)
  await page.setContent('<style>body { margin: 0 }</style><div id="resizing" style="width:1200px">resizing</div>')
  await page.evaluate(() => {
    window.layoutFrames = 0
    function settle() {
      window.layoutFrames++
      if (window.layoutFrames === 4) document.querySelector('#resizing').style.width = '100%'
      else requestAnimationFrame(settle)
    }
    requestAnimationFrame(settle)
  })
  await assertNoHorizontalOverflow(page)
  assert.ok(await page.evaluate(() => window.layoutFrames >= 4))
  await page.setContent('<style>body { margin: 0 }</style><div class="too-wide" style="width:1200px">overflow</div>')
  await assert.rejects(assertNoHorizontalOverflow(page, { timeout: 250 }), /Persistent horizontal overflow:.*too-wide/)
  const directory = path.join(root, 'test/.artifacts/reports/r8-final')
  await mkdir(directory, { recursive: true })
  await writeFile(path.join(directory, 'viewport-layout.json'), JSON.stringify({ passed: true,
    fitting_layout: true, delayed_layout_settles: true, persistent_overflow_rejected: true,
    width_tolerance_px: 0 }, null, 2))
  console.log('R8 viewport layout: fit, delayed resize and permanent overflow checks passed')
} finally {
  await browser.close()
}
