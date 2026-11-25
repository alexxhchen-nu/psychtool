import { expect, test } from '@playwright/test'

// Full PT-01 walking skeleton against the real backend (webServer in
// playwright.config.ts). The server runs the offline FakeTransport by
// default, so this test needs no API key and no network access.
//
// Prerequisite: build the SPA first (`cd web && bun run build`) so FastAPI
// can serve web/dist.

const BANNER =
  'Please note: This prototype is not HIPAA compliant yet. Do not enter real patient information. Use only synthetic or separately approved practice materials.'

const SYNTHETIC_TEXT =
  'Synthetic practice note: the fictional student completed a timed reading exercise.\n\nSynthetic follow-up: the fictional student described the exercise as easy.'

test('walking skeleton: case -> paste -> evidence -> egress -> save -> reload', async ({ page }) => {
  await page.goto('/')

  // Persistent privacy banner is visible before anything else.
  await expect(page.getByText(BANNER)).toBeVisible()

  // 1. Create a new case in the browser.
  const caseId = `e2e-${Date.now()}`
  await page.getByLabel('New case ID').fill(caseId)
  await page.getByRole('button', { name: 'Create case' }).click()
  // The created case becomes the selected value of the topbar Case combobox.
  const casePicker = page.getByRole('combobox', { name: 'Case', exact: true })
  await expect(casePicker).toHaveValue(caseId)
  // The form is cleared for the next case.
  await expect(page.getByLabel('New case ID')).toHaveValue('')

  // 2. Paste a short synthetic text block, confirming it is synthetic.
  await page.getByRole('button', { name: 'Paste synthetic text' }).click()
  const pastePanel = page.locator('.paste-panel')
  await pastePanel.getByLabel(/Anonymous material ID/).fill('e2e-material')
  await pastePanel.getByLabel('Title (required)').fill('E2E synthetic note')
  await pastePanel.getByLabel('Provider (required)').fill('synthetic author')
  await pastePanel.getByLabel('Date (required)').fill('2026-11-20')
  await pastePanel.getByLabel(/Synthetic text/).fill(SYNTHETIC_TEXT)
  await pastePanel
    .getByRole('checkbox', { name: /entirely synthetic/ })
    .check()
  await pastePanel.getByRole('button', { name: 'Save pasted material' }).click()
  await expect(pastePanel.getByText('Material saved')).toBeVisible()

  // 3. Rule-extracted evidence: create candidates and accept one.
  // The toggle lives inside the paste panel's saved-material confirmation;
  // the intake review panel itself is a sibling section.
  await pastePanel.getByRole('button', { name: 'Review intake claims' }).click()
  const intake = page.locator('.intake-panel')
  await intake.getByRole('button', { name: 'Create candidates' }).click()
  const firstCard = intake.locator('.intake-card').first()
  await expect(firstCard).toBeVisible()
  // ADR 0017: the card cites stored sentence evidence (never a bare passage).
  await expect(firstCard.getByTestId('cited-evidence-ids')).toContainText(/ev_[0-9a-f]{24}/)
  await intake.getByRole('button', { name: 'Accept claim' }).first().click()
  await expect(page.locator('.case-meta')).toContainText('1 claims')

  // The claim is listed as a selectable source for the section editor.
  await expect(page.locator('.claim-list')).toContainText('e2e-material')

  // 4. Select the History section, attach the accepted evidence as a source,
  // then prepare -> review -> approve -> send through the egress gateway
  // (FakeTransport). She reads the complete outgoing text, confirms the
  // review, then approves. The pinned e2e tier is synthetic, so the
  // tier-required reason field is the only free-text field.
  await page.locator('.section-rail').getByRole('button', { name: /History/ }).click()
  // The evidence must flow into the chapter: check it in the source list so
  // the prepared request carries its passage, not an empty source_material.
  const evidenceCheckbox = page.getByRole('checkbox', { name: /e2e-material/ })
  await evidenceCheckbox.check()
  const egress = page.locator('.egress-panel')
  await egress.getByRole('button', { name: 'Prepare request' }).click()
  await expect(egress.getByText('Prepared — review required')).toBeVisible()
  // Read the full exact outgoing text before approving.
  const preview = egress.getByRole('region', { name: 'Exact model input' })
  await expect(preview).toContainText('Synthetic practice note')
  await egress.getByLabel(/Synthetic approval reason/).fill('Reviewed full synthetic outgoing text')
  await egress.getByRole('checkbox', { name: /reviewed the complete input/ }).check()
  await egress.getByRole('button', { name: 'Approve request' }).click()
  await expect(egress.getByText('Approved — not sent')).toBeVisible()
  await egress.getByRole('button', { name: 'Send once' }).click()
  await expect(egress.getByText('Sent — no resend')).toBeVisible()

  // The fake text lands in the editor as unsaved text.
  const editor = page.getByLabel('Section text')
  await expect(editor).toHaveValue(/FAKE OFFLINE RESPONSE/)
  await expect(page.getByText('Unsaved changes').or(page.getByText(/Generated draft is in the editor/))).toBeVisible()

  // 5. Save the section.
  await page.getByRole('button', { name: 'Save section' }).click()
  await expect(page.getByText('Section saved.')).toBeVisible()

  // 6. Reload: case, material, evidence and saved section text are still there.
  await page.reload()
  await expect(page.getByText(BANNER)).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Case', exact: true })).toHaveValue(caseId)
  await expect(page.locator('.case-meta')).toContainText('1 materials')
  await expect(page.locator('.case-meta')).toContainText('1 claims')
  await page.locator('.section-rail').getByRole('button', { name: /History/ }).click()
  await expect(page.getByLabel('Section text')).toHaveValue(/FAKE OFFLINE RESPONSE/)
  // The saved section still has the accepted evidence attached as a source.
  await expect(page.getByRole('checkbox', { name: /e2e-material/ })).toBeChecked()
})
