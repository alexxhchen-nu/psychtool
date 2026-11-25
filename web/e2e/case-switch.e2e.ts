import { expect, test, type Page } from '@playwright/test'

// R1-AC2 browser check: two cases with different pasted synthetic text and
// accepted evidence each; switching the topbar Case combobox must show only
// the current case's materials and evidence. Accepted claims render with
// their text in .claim-list, so the pasted markers appear there.
//
// Prerequisite: build the SPA first (`cd web && bun run build`) so FastAPI
// can serve web/dist. The webServer in playwright.config.ts provides a fresh
// temp SQLite database per run and pins the offline fake transport.

const TEXT_A =
  'Synthetic alpha note: the fictional participant enjoys morning chess puzzles.'
const TEXT_B =
  'Synthetic beta note: the fictional participant prefers evening swimming drills.'
const MARKER_A = 'morning chess puzzles'
const MARKER_B = 'evening swimming drills'

async function createCaseWithEvidence(
  page: Page,
  caseId: string,
  materialId: string,
  text: string,
) {
  await page.getByLabel('New case ID').fill(caseId)
  await page.getByRole('button', { name: 'Create case' }).click()
  const casePicker = page.getByRole('combobox', { name: 'Case', exact: true })
  await expect(casePicker).toHaveValue(caseId)

  await page.getByRole('button', { name: 'Paste synthetic text' }).click()
  const pastePanel = page.locator('.paste-panel')
  await pastePanel.getByLabel(/Anonymous material ID/).fill(materialId)
  await pastePanel.getByLabel('Title (required)').fill(`E2E note for ${caseId}`)
  await pastePanel.getByLabel('Provider (required)').fill('synthetic author')
  await pastePanel.getByLabel('Date (required)').fill('2026-11-24')
  await pastePanel.getByLabel(/Synthetic text/).fill(text)
  await pastePanel.getByRole('checkbox', { name: /entirely synthetic/ }).check()
  await pastePanel.getByRole('button', { name: 'Save pasted material' }).click()
  await expect(pastePanel.getByText('Material saved')).toBeVisible()

  // Accept one piece of evidence for this case.
  await pastePanel.getByRole('button', { name: 'Review intake claims' }).click()
  const intake = page.locator('.intake-panel')
  await intake.getByRole('button', { name: 'Create candidates' }).click()
  await expect(intake.locator('.intake-card').first()).toBeVisible()
  await intake.getByRole('button', { name: 'Accept claim' }).first().click()
  await expect(page.locator('.case-meta')).toContainText('1 claims')
}

test('case switch: each case shows only its own material and evidence', async ({ page }) => {
  await page.goto('/')

  const suffix = Date.now()
  const caseA = `e2e-a-${suffix}`
  const caseB = `e2e-b-${suffix}`

  await createCaseWithEvidence(page, caseA, 'mat-alpha', TEXT_A)
  await createCaseWithEvidence(page, caseB, 'mat-beta', TEXT_B)

  const casePicker = page.getByRole('combobox', { name: 'Case', exact: true })

  // Currently on case B: only B's material and evidence are visible.
  await expect(casePicker).toHaveValue(caseB)
  await expect(page.locator('.claim-list')).toContainText('mat-beta')
  await expect(page.locator('.claim-list')).not.toContainText('mat-alpha')
  await expect(page.locator('.claim-list')).toContainText(MARKER_B)
  await expect(page.locator('.claim-list')).not.toContainText(MARKER_A)

  // Switch to case A: only A's material and evidence are visible.
  await casePicker.selectOption(caseA)
  await expect(page.locator('.case-meta')).toContainText('1 materials')
  await expect(page.locator('.case-meta')).toContainText('1 claims')
  await expect(page.locator('.claim-list')).toContainText('mat-alpha')
  await expect(page.locator('.claim-list')).not.toContainText('mat-beta')
  await expect(page.locator('.claim-list')).toContainText(MARKER_A)
  await expect(page.locator('.claim-list')).not.toContainText(MARKER_B)

  // Switch back to case B: the view flips accordingly.
  await casePicker.selectOption(caseB)
  await expect(page.locator('.claim-list')).toContainText('mat-beta')
  await expect(page.locator('.claim-list')).not.toContainText('mat-alpha')
  await expect(page.locator('.claim-list')).toContainText(MARKER_B)
  await expect(page.locator('.claim-list')).not.toContainText(MARKER_A)
})
