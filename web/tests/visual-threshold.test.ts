import { expect, test } from 'bun:test'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const src = readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), '../e2e/visual.e2e.ts'),
  'utf8',
)

test('agreed screenshot-diff threshold is 2%', () => {
  expect(src).toContain('const THRESHOLD = 0.02')
  expect(src).not.toMatch(/const THRESHOLD = 0\.05\b/)
  expect(src).toContain('under 2%')
})
