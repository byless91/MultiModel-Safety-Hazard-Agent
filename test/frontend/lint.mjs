/** Use a repository cwd so ESLint also checks tests outside frontend/. */
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../../', import.meta.url))
const require = createRequire(new URL('../../frontend/package.json', import.meta.url))
const { ESLint } = require('eslint')
const eslint = new ESLint({
  cwd: root,
  overrideConfigFile: fileURLToPath(new URL('../../frontend/eslint.config.js', import.meta.url)),
})
const results = await eslint.lintFiles(['frontend', 'test/frontend/**/*.{ts,mjs}'])
const formatter = await eslint.loadFormatter('stylish')
const output = formatter.format(results)
if (output) process.stdout.write(output)
if (results.some((result) => result.errorCount > 0)) process.exitCode = 1
