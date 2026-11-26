import { expect, test } from '@playwright/test'
import { acceptFirstClaim, openSyntheticWorkspace } from './workspace-helpers'

// PT-12 (GROK-42, R10): unsourced sentences get a wavy Unverified mark,
// the mark survives save and reload, My judgment is not treated as a
// material fact, and a Summary draft with recommendation wording is refused.

async function generateHistory(page: import('@playwright/test').Page) {
  const claim = page.getByRole('checkbox', { name: /e2e-material/ })
  await claim.check()
  const egress = page.locator('.egress-panel')
  await egress.getByRole('button', { name: 'Prepare request' }).click()
  await expect(egress.getByText('Prepared — review required')).toBeVisible()
  await egress.getByLabel(/Synthetic approval reason/).fill('Reviewed full synthetic outgoing text')
  await egress.getByRole('checkbox', { name: /reviewed the complete input/ }).check()
  await egress.getByRole('button', { name: 'Approve request' }).click()
  await expect(egress.getByText('Approved — not sent')).toBeVisible()
  await egress.getByRole('button', { name: 'Send once' }).click()
  await expect(egress.getByText('Sent — no resend')).toBeVisible()
}

test('History: unsourced generated sentences are Unverified and the mark survives save and reload', async ({ page }) => {
  const caseId = await openSyntheticWorkspace(page)
  await acceptFirstClaim(page)
  await generateHistory(page)

  const editor = page.getByLabel('Section text')
  await expect(editor).toHaveValue(/FAKE OFFLINE RESPONSE/)
  await expect(page.getByTestId('save-state')).toHaveText('Unsaved changes')

  const unverified = page.getByTestId('sentence-unverified')
  await expect(unverified.first()).toBeVisible()
  await expect(unverified.first()).toHaveCSS('text-decoration-style', 'wavy')
  await expect(page.getByText('Unverified · no source found').first()).toBeVisible()

  await page.getByRole('button', { name: 'Save section' }).click()
  await expect(page.getByText('Section saved.')).toBeVisible()
  await expect(page.getByTestId('save-state')).toHaveText('Saved')
  await expect(page.getByTestId('sentence-unverified').first()).toBeVisible()

  await page.reload()
  await page.getByRole('combobox', { name: 'Case', exact: true }).selectOption(caseId)
  await page.locator('.section-rail').getByRole('button', { name: /History/ }).click()
  await expect(page.getByLabel('Section text')).toHaveValue(/FAKE OFFLINE RESPONSE/)
  await expect(page.getByTestId('sentence-unverified').first()).toBeVisible()
  await expect(page.getByTestId('sentence-unverified').first()).toHaveCSS('text-decoration-style', 'wavy')
})

test('History: marking an Unverified sentence as My judgment survives save', async ({ page }) => {
  const caseId = await openSyntheticWorkspace(page)
  await acceptFirstClaim(page)
  await generateHistory(page)

  await page.getByTestId('sentence-unverified').first().click()
  await expect(page.getByTestId('unverified-hint')).toBeVisible()
  await page.getByTestId('mark-my-judgment').click()
  await expect(page.getByTestId('sentence-my_judgment').first()).toBeVisible()
  await expect(page.getByText('My judgment').first()).toBeVisible()

  await page.getByRole('button', { name: 'Save section' }).click()
  await expect(page.getByText('Section saved.')).toBeVisible()

  await page.reload()
  await page.getByRole('combobox', { name: 'Case', exact: true }).selectOption(caseId)
  await page.locator('.section-rail').getByRole('button', { name: /History/ }).click()
  await expect(page.getByTestId('sentence-my_judgment').first()).toBeVisible()
})

test('Summary: a draft with recommendation wording is refused and not saved', async ({ page }) => {
  const caseId = await openSyntheticWorkspace(page)
  await page.locator('.section-rail').getByRole('button', { name: /^Summary,/ }).click()
  await page.getByLabel('Section text').fill('I recommend weekly tutoring.')
  await page.getByRole('button', { name: 'Save section' }).click()
  await expect(page.getByRole('alert')).toContainText('a Summary draft must not contain diagnostic or recommendation wording')

  await page.reload()
  await page.getByRole('combobox', { name: 'Case', exact: true }).selectOption(caseId)
  await page.locator('.section-rail').getByRole('button', { name: /^Summary,/ }).click()
  await expect(page.getByLabel('Section text')).toHaveValue('')
})
