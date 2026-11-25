import { expect, test } from '@playwright/test'
import { acceptFirstClaim, openSyntheticWorkspace } from './workspace-helpers'

// PT-11 (GROK-41, R9): the section editor keeps generated text unsaved and
// visible, preserves it across a section switch, and never fills the
// clinician-authored impressions / recommendations sections. Real backend,
// FakeTransport, synthetic data only.

test('History: generated text is unsaved, claims stay attached, save survives switch and reload', async ({ page }) => {
  const caseId = await openSyntheticWorkspace(page)
  await acceptFirstClaim(page)

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

  const editor = page.getByLabel('Section text')
  await expect(editor).toHaveValue(/FAKE OFFLINE RESPONSE/)
  await expect(page.getByTestId('save-state')).toHaveText('Unsaved changes')
  await expect(claim).toBeChecked()

  // Switching away and back before saving keeps the unsaved generated text.
  const rail = page.locator('.section-rail')
  await rail.getByRole('button', { name: /Methods/ }).click()
  await rail.getByRole('button', { name: /History/ }).click()
  await expect(page.getByLabel('Section text')).toHaveValue(/FAKE OFFLINE RESPONSE/)
  await expect(page.getByTestId('save-state')).toHaveText('Unsaved changes')
  await expect(page.getByRole('checkbox', { name: /e2e-material/ })).toBeChecked()

  await page.getByRole('button', { name: 'Save section' }).click()
  await expect(page.getByText('Section saved.')).toBeVisible()
  await expect(page.getByTestId('save-state')).toHaveText('Saved')

  // Switch away and back: the editor is not remounted, saved text remains.
  await rail.getByRole('button', { name: /Methods/ }).click()
  await rail.getByRole('button', { name: /History/ }).click()
  await expect(page.getByLabel('Section text')).toHaveValue(/FAKE OFFLINE RESPONSE/)
  await expect(page.getByTestId('save-state')).toHaveText('Saved')

  // Full reload: re-select this case (the picker defaults to workspaces[0]).
  await page.reload()
  const picker = page.getByRole('combobox', { name: 'Case', exact: true })
  await picker.selectOption(caseId)
  await expect(picker).toHaveValue(caseId)
  await page.locator('.section-rail').getByRole('button', { name: /History/ }).click()
  await expect(page.getByLabel('Section text')).toHaveValue(/FAKE OFFLINE RESPONSE/)
  await expect(page.getByRole('checkbox', { name: /e2e-material/ })).toBeChecked()
})

test('Clinical Impressions and Recommendations are written by her, never generated', async ({ page }) => {
  const caseId = await openSyntheticWorkspace(page)
  await acceptFirstClaim(page)

  const rail = page.locator('.section-rail')
  const canvas = page.locator('.section-canvas')
  const ownText: Record<string, string> = {
    'Clinical Impressions': 'My own synthesized impression, written and reviewed by me.',
    Recommendations: 'My own recommendation, written and reviewed by me.',
  }

  for (const [title, text] of Object.entries(ownText)) {
    await rail.getByRole('button', { name: new RegExp(title) }).click()

    // No model request path at all for this section.
    await expect(canvas.locator('.egress-panel')).toHaveCount(0)
    await expect(canvas.getByRole('button', { name: /Prepare request|Approve request|Send once/ })).toHaveCount(0)

    // Clear notice covering both clinician-authored sections.
    const notice = canvas.getByTestId('clinician-authored-notice')
    await expect(notice).toBeVisible()
    await expect(notice).toContainText('You write this section')
    await expect(notice).toContainText('Clinical impressions')
    await expect(notice).toContainText('recommendations')
    await expect(notice).toContainText('never sent to the AI assistant')

    await expect(canvas.getByTestId('you-write-this')).toHaveText('You write this')
    const editor = canvas.getByLabel('Section text')
    await expect(editor).toHaveValue('')

    // Attaching a source prompt must not insert generated body text.
    const claim = canvas.getByRole('checkbox', { name: /e2e-material/ })
    await claim.check()
    await expect(editor).toHaveValue('')
    await expect(canvas.getByTestId('save-state')).toHaveText('Unsaved changes')

    await editor.fill(text)
    await expect(canvas.getByTestId('save-state')).toHaveText('Unsaved changes')
    await page.getByRole('button', { name: 'Save section' }).click()
    await expect(page.getByText('Section saved.')).toBeVisible()
    await expect(canvas.getByTestId('save-state')).toHaveText('Saved')
  }

  await page.reload()
  await page.getByRole('combobox', { name: 'Case', exact: true }).selectOption(caseId)
  for (const [title, text] of Object.entries(ownText)) {
    await page.locator('.section-rail').getByRole('button', { name: new RegExp(title) }).click()
    await expect(page.getByLabel('Section text')).toHaveValue(text)
    await expect(page.locator('.section-canvas .egress-panel')).toHaveCount(0)
  }
})

test('one primary action at a time: send step, then Save, then Approve section', async ({ page }) => {
  await openSyntheticWorkspace(page)
  await acceptFirstClaim(page)

  const canvas = page.locator('.section-canvas')
  const enabledPrimary = canvas.locator('.primary-button:not([disabled])')
  await expect(page.getByRole('button', { name: 'Create case' })).toHaveClass(/secondary-button/)

  const claim = page.getByRole('checkbox', { name: /e2e-material/ })
  await claim.check()

  const egress = page.locator('.egress-panel')
  await egress.getByRole('button', { name: 'Prepare request' }).click()
  await expect(egress.getByText('Prepared — review required')).toBeVisible()
  // Until the review checklist is complete, the send pane has no enabled primary.
  await expect(egress.getByRole('button', { name: 'Approve request' })).toBeDisabled()

  await egress.getByLabel(/Synthetic approval reason/).fill('Reviewed full synthetic outgoing text')
  await egress.getByRole('checkbox', { name: /reviewed the complete input/ }).check()
  await expect(egress.getByRole('button', { name: 'Approve request' })).toHaveClass(/primary-button/)
  await expect(egress.getByRole('button', { name: 'Approve request' })).toBeEnabled()
  // The save bar steps down while Approve request is the view's one primary.
  await expect(canvas.getByTestId('save-section')).toHaveClass(/secondary-button/)
  await expect(canvas.getByTestId('approve-section')).toHaveClass(/secondary-button/)
  await expect(enabledPrimary).toHaveCount(1)
  await expect(enabledPrimary).toHaveText('Approve request')

  await egress.getByRole('button', { name: 'Approve request' }).click()
  await expect(egress.getByText('Approved — not sent')).toBeVisible()
  await expect(enabledPrimary).toHaveCount(1)
  await expect(enabledPrimary).toHaveText('Send once')
  await expect(canvas.getByTestId('save-section')).toHaveClass(/secondary-button/)

  await egress.getByRole('button', { name: 'Send once' }).click()
  await expect(egress.getByText('Sent — no resend')).toBeVisible()
  await expect(page.getByLabel('Section text')).toHaveValue(/FAKE OFFLINE RESPONSE/)
  await expect(page.getByTestId('save-state')).toHaveText('Unsaved changes')
  // Generated unsaved text: Save section is the one primary.
  await expect(canvas.getByTestId('save-section')).toHaveClass(/primary-button/)
  await expect(enabledPrimary).toHaveCount(1)
  await expect(enabledPrimary).toHaveText('Save section')

  await canvas.getByTestId('save-section').click()
  await expect(page.getByText('Section saved.')).toBeVisible()
  await expect(page.getByTestId('save-state')).toHaveText('Saved')
  // Saved, non-empty, not yet approved: Approve section is the one primary.
  await expect(canvas.getByTestId('approve-section')).toHaveClass(/primary-button/)
  await expect(canvas.getByTestId('save-section')).toHaveClass(/secondary-button/)
  await expect(canvas.getByTestId('save-section')).toBeDisabled()
  await expect(enabledPrimary).toHaveCount(1)
  await expect(enabledPrimary).toHaveText('Approve section')
})
