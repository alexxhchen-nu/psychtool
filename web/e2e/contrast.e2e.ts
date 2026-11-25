import { expect, test } from '@playwright/test'
import { createRequire } from 'node:module'
import { openSyntheticWorkspace } from './workspace-helpers'

// PT-10: WCAG 2.x contrast on the SPA, reusing the prototype harness
// (web/scripts/contrast.js). Text ≥4.5:1 normal, ≥3:1 large; non-text /
// 1.4.11 (focus rings, form borders) ≥3:1. Zero failures is required.

const require = createRequire(import.meta.url)
const contrast = require('../scripts/contrast.js') as {
  audit: (page: unknown, label: string) => Promise<ContrastRow[]>
  interact: (page: unknown, label: string) => Promise<ContrastRow[]>
}

interface ContrastRow {
  kind: string
  where?: string
  text?: string
  fg?: string
  bg?: string
  ratio: number
  need: number
  pass: boolean
  disabled?: boolean
}

function formatFailures(rows: ContrastRow[]): string {
  return rows
    .filter((row) => !row.pass)
    .slice(0, 20)
    .map((row) => `${row.kind} ${row.where ?? ''} "${row.text ?? ''}" ${row.fg}/${row.bg} ${row.ratio}<${row.need}`)
    .join('\n')
}

test('contrast check has 0 failures on the three-column workspace', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await openSyntheticWorkspace(page)
  await page.getByRole('button', { name: 'Evidence' }).click()
  const item = page.getByTestId('evidence-item').first()
  if (await item.count()) await item.click()
  await page.evaluate(() => document.fonts?.ready)

  const measured = [
    ...(await contrast.audit(page, 'spa')),
    ...(await contrast.interact(page, 'spa')),
  ]
  const failures = measured.filter((row) => !row.pass)
  const min = measured.reduce((best, row) => (row.ratio < best.ratio ? row : best), measured[0])
  // Printed so CI and the PT-10 report can quote the numbers.
  console.log(
    `CONTRAST spa: ${measured.length} measured, ${failures.length} failures, min ${min ? min.ratio + ':1' : '-'} (${min?.kind ?? ''} ${min?.where ?? ''})`,
  )
  if (failures.length) console.log(formatFailures(failures))
  expect(failures, formatFailures(failures)).toEqual([])
  expect(measured.length).toBeGreaterThan(0)
})
