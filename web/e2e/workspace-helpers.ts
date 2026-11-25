import { expect, type Page } from '@playwright/test'

export const SYNTHETIC_TEXT =
  'Synthetic practice note: the fictional student completed a timed reading exercise.\n\n'
  + 'Synthetic follow-up: the fictional student described the exercise as easy.'

/** Create a synthetic case, paste a short note, and open the History section
 * so the three-column workspace is on screen. */
export async function openSyntheticWorkspace(page: Page): Promise<string> {
  await page.goto('/')
  const caseId = `e2e-r8-${Date.now()}`
  await page.getByLabel('New case ID').fill(caseId)
  await page.getByRole('button', { name: 'Create case' }).click()
  await expect(page.getByRole('combobox', { name: 'Case', exact: true })).toHaveValue(caseId)

  await page.getByRole('button', { name: 'Paste synthetic text' }).click()
  const pastePanel = page.locator('.paste-panel')
  await pastePanel.getByLabel(/Anonymous material ID/).fill('e2e-material')
  await pastePanel.getByLabel('Title (required)').fill('E2E synthetic note')
  await pastePanel.getByLabel('Provider (required)').fill('synthetic author')
  await pastePanel.getByLabel('Date (required)').fill('2026-11-20')
  await pastePanel.getByLabel(/Synthetic text/).fill(SYNTHETIC_TEXT)
  await pastePanel.getByRole('checkbox', { name: /entirely synthetic/ }).check()
  await pastePanel.getByRole('button', { name: 'Save pasted material' }).click()
  await expect(pastePanel.getByText('Material saved')).toBeVisible()

  await page.locator('.section-rail').getByRole('button', { name: /History/ }).click()
  await expect(page.locator('.report-grid')).toBeVisible()
  await expect(page.locator('#section-text')).toBeVisible()
  return caseId
}

export async function acceptFirstClaim(page: Page): Promise<void> {
  await page.locator('.case-actions').getByRole('button', { name: 'Review intake claims' }).click()
  const intake = page.locator('.intake-panel')
  await intake.getByRole('button', { name: 'Create candidates' }).click()
  await expect(intake.locator('.intake-card').first()).toBeVisible()
  await intake.getByRole('button', { name: 'Accept claim' }).first().click()
  await expect(page.getByTestId('claim-source').first()).toBeVisible()
}
