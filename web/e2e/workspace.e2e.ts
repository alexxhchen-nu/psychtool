import { expect, test } from '@playwright/test'
import { acceptFirstClaim, openSyntheticWorkspace } from './workspace-helpers'

// PT-10 / GROK-40 / R8: three-column workspace, source card shows only real
// locations, and the prototype Export control is not ported (Q7).

test('R8-AC1 R8-AC2: clicking evidence or a cited claim fills the right-column source card; the editor stays visible; no invented page', async ({ page }) => {
  await openSyntheticWorkspace(page)

  await page.getByRole('button', { name: 'Evidence' }).click()
  const evidenceItem = page.getByTestId('evidence-item').first()
  await expect(evidenceItem).toBeVisible()
  await evidenceItem.click()

  const card = page.getByTestId('source-card')
  await expect(card).toBeVisible()
  await expect(card.getByText(/Quoted passage/)).toBeVisible()
  await expect(card.locator('.source-quote')).not.toHaveText('')
  await expect(card.getByText(/Source role|From:/)).toBeVisible()
  await expect(card.getByTestId('source-status')).toBeVisible()
  const location = page.getByTestId('source-location')
  await expect(location).toBeVisible()
  await expect(location).not.toHaveText(/page\s*\d+/i)
  await expect(card).toContainText(/Only locations recorded in the case are shown/)

  // Middle editor stays a visible sibling, not covered by a modal.
  const editor = page.locator('#section-text')
  await expect(editor).toBeVisible()
  await expect(page.locator('.report-grid')).toBeVisible()
  await expect(page.locator('[role="dialog"], [aria-modal="true"]')).toHaveCount(0)

  await acceptFirstClaim(page)
  await page.getByTestId('claim-source').first().click()
  await expect(card).toBeVisible()
  await expect(page.getByTestId('source-location')).not.toHaveText(/page\s*\d+/i)
  await expect(editor).toBeVisible()
  await expect(page.locator('[role="dialog"], [aria-modal="true"]')).toHaveCount(0)
})

test('Q7: there is no Export entry in the UI', async ({ page }) => {
  await openSyntheticWorkspace(page)
  await expect(page.getByRole('button', { name: /export/i })).toHaveCount(0)
  await expect(page.getByRole('link', { name: /export/i })).toHaveCount(0)
  await expect(page.getByRole('menuitem', { name: /export/i })).toHaveCount(0)
  await expect(page.getByText(/Export saved draft/i)).toHaveCount(0)
})
