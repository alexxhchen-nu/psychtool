import { spawnSync } from 'node:child_process'
import { expect, test } from '@playwright/test'

// PT-09 chunk 3 (GROK-39, R6 / ADR 0018) browser check against the real
// backend (FakeTransport, synthetic data only): after a category correction
// on a cited evidence item, the UI shows the server's exact toast, the
// section editor's UNSAVED textarea text survives untouched, the open
// approved section's pill returns to Needs review, and the prepared egress
// request tied to the item is invalidated and cannot be sent.
//
// Prerequisite: build the SPA first (`cd web && bun run build`).

const TEACHER_MD = 'Teacher says he reads slowly in class.\n\nThe weather was cloudy that week.\n'
const TEACHER_QUOTE = 'Teacher says he reads slowly in class'
const SAVED_SECTION_TEXT = 'Saved history section text.'
const UNSAVED_TEXT = 'Her unsaved draft sentence that must survive the correction.'

const CASCADE_TOAST =
  'Your change was saved. 1 citing statement is no longer marked verified. ' +
  '1 section was returned to Needs review. ' +
  '1 prepared request was invalidated and must be prepared again. ' +
  'Unsaved text was not changed.'

async function sessionHeaders(page: import('@playwright/test').Page) {
  const token = await page.locator('meta[name="psychtool-session"]').getAttribute('content')
  return { 'X-Psychtool-Token': token ?? '' }
}

test('R6: category correction shows the server toast, keeps unsaved text, invalidates prepared egress', async ({ page }) => {
  await page.goto('/')

  // 1. Create a case and upload one synthetic note (API, after UI confirm).
  const caseId = `e2e-r6-${Date.now()}`
  await page.getByLabel('New case ID').fill(caseId)
  await page.getByRole('button', { name: 'Create case' }).click()
  await expect(page.getByRole('combobox', { name: 'Case', exact: true })).toHaveValue(caseId)

  await page.getByRole('button', { name: 'Upload material' }).click()
  const upload = page.locator('.upload-panel')
  await upload
    .getByRole('checkbox', { name: /only synthetic or separately approved materials/ })
    .check()
  await upload.getByRole('button', { name: 'Confirm and enable upload' }).click()
  await expect(upload.getByText(/Before the first upload, confirm/)).toBeHidden()

  const headers = await sessionHeaders(page)
  const materialResponse = await page.request.post(`/api/workspaces/${caseId}/materials`, {
    headers,
    multipart: {
      file: { name: 'note.md', mimeType: 'text/markdown', buffer: Buffer.from(TEACHER_MD, 'utf-8') },
      material_id: 'note',
      title: 'School note',
      provider: 'synthetic author',
      date: '2026-11-24',
      kind: 'case',
    },
  })
  expect(materialResponse.ok(), await materialResponse.text()).toBe(true)

  // 2. Find the cited evidence item, accept a claim citing it, verify the
  // claim (no API route exists; the store is the same database), save an
  // approved History section citing the claim, and prepare one egress
  // request that references it.
  const evidenceResponse = await page.request.get(`/api/workspaces/${caseId}/evidence`, { headers })
  expect(evidenceResponse.ok()).toBe(true)
  const evidencePayload = await evidenceResponse.json()
  const item = evidencePayload.items.find((row: { quote: string }) => row.quote.includes(TEACHER_QUOTE))
  expect(item).toBeTruthy()
  const evidenceId: string = item.id

  // Accept the stored suggestion that cites this evidence (ids and source
  // text must match the suggestion exactly; a hand-built body is rejected).
  const suggestionsResponse = await page.request.get(
    `/api/workspaces/${caseId}/materials/note/suggestions?provider_role=self_report`,
    { headers },
  )
  expect(suggestionsResponse.ok(), await suggestionsResponse.text()).toBe(true)
  const suggestion = (await suggestionsResponse.json()).find(
    (row: { evidence_ids?: string[] }) => (row.evidence_ids ?? []).includes(evidenceId),
  )
  expect(suggestion, 'expected a suggestion citing the teacher evidence').toBeTruthy()
  const claimResponse = await page.request.post(`/api/workspaces/${caseId}/claims`, {
    headers,
    data: suggestion,
  })
  expect(claimResponse.ok(), await claimResponse.text()).toBe(true)
  const claimId: string = (await claimResponse.json()).id

  const sectionResponse = await page.request.put(`/api/workspaces/${caseId}/sections/history`, {
    headers,
    data: {
      template_id: 'intake-report',
      template_version: 1,
      text: SAVED_SECTION_TEXT,
      claim_ids: [claimId],
      status: 'approved',
      reviewer: 'Dr. Synthetic',
    },
  })
  expect(sectionResponse.ok(), await sectionResponse.text()).toBe(true)

  const prepareResponse = await page.request.post(`/api/workspaces/${caseId}/egress/prepare`, {
    headers,
    data: {
      template_id: 'intake-report',
      template_version: 1,
      section_id: 'history',
      claim_ids: [claimId],
      instructions: 'Write the history section.',
      purpose: 'section_generation',
    },
  })
  expect(prepareResponse.ok(), await prepareResponse.text()).toBe(true)
  const prepared = await prepareResponse.json()
  expect(prepared.status).toBe('prepared')

  // The browser prototype has no claim-verification route; mark it verified
  // through CaseStore on the same temp database the webServer uses.
  const dbPath = process.env.PSYCHTOOL_E2E_DB_PATH
  expect(dbPath).toBeTruthy()
  const verify = spawnSync(
    'uv',
    [
      'run',
      'python',
      '-c',
      'import sys\n'
        + 'from psychtool.store.sqlite_store import SqliteStore\n'
        + 'store = SqliteStore(sys.argv[1])\n'
        + "store.case(sys.argv[2]).mark_claim_status(sys.argv[3], \"verified\")\n",
      dbPath!,
      caseId,
      claimId,
    ],
    { cwd: '..', encoding: 'utf8' },
  )
  expect(verify.status, verify.stderr || verify.stdout).toBe(0)

  // Seed sessionStorage so the egress panel restores the API-prepared request
  // after reload (the UI only persists ids it itself prepared).
  const egressStorageKey = `psychtool.egress.${JSON.stringify([caseId, 'intake-report', 1, 'history'])}`
  await page.evaluate(
    ({ key, id }) => sessionStorage.setItem(key, id),
    { key: egressStorageKey, id: prepared.request_id },
  )

  // 3. Reload so the UI sees the API-written state; open the History
  // section and type UNSAVED text into the editor.
  await page.reload()
  await page.getByRole('combobox', { name: 'Case', exact: true }).selectOption(caseId)
  await page.locator('.section-rail').getByRole('button', { name: /History/ }).click()
  const editor = page.getByLabel('Section text')
  await expect(editor).toHaveValue(SAVED_SECTION_TEXT)
  await expect(page.locator('.egress-panel').getByText('Prepared — review required')).toBeVisible()
  await editor.fill(UNSAVED_TEXT)
  await expect(page.getByText('Unsaved changes')).toBeVisible()

  // 4. Change the cited item's category in the Evidence panel.
  await page.getByRole('button', { name: 'Evidence' }).click()
  // The category select lives on the list item, beside the evidence-item button
  // (same locator pattern as categories.e2e.ts).
  const row = page.locator('li', {
    has: page.getByTestId('evidence-item').filter({ hasText: TEACHER_QUOTE }),
  })
  await expect(row.getByLabel('Change category')).toBeEnabled()
  await row.getByLabel('Change category').selectOption('other')

  // 5. The server's exact toast is shown verbatim.
  const toast = page.getByTestId('correction-toast')
  await expect(toast).toBeVisible()
  await expect(toast).toHaveText(CASCADE_TOAST)

  // 6. The unsaved textarea text survived the correction, byte for byte.
  await expect(editor).toHaveValue(UNSAVED_TEXT)

  // 7. The prepared egress request is invalidated: the panel drops back to
  // "prepare again" and the request itself reads invalidated via the API.
  const egressPanel = page.locator('.egress-panel')
  await expect(egressPanel.getByText('Invalidated — prepare again')).toBeVisible()
  await expect(egressPanel.getByText(/This request is no longer current/)).toBeVisible()
  await expect(egressPanel.getByRole('button', { name: 'Send once' })).toHaveCount(0)
  const requestResponse = await page.request.get(
    `/api/workspaces/${caseId}/egress/${prepared.request_id}`,
    { headers },
  )
  expect((await requestResponse.json()).status).toBe('invalidated')

  // 8. The claim is pending again and the section returned to Needs review
  // on the server — with the saved text untouched.
  const claimsResponse = await page.request.get(`/api/workspaces/${caseId}/claims`, { headers })
  const claims = await claimsResponse.json()
  expect(claims.find((claim: { id: string }) => claim.id === claimId).verification_status).toBe('pending')
  const sectionsResponse = await page.request.get(
    `/api/workspaces/${caseId}/sections?template_id=intake-report`,
    { headers },
  )
  const history = (await sectionsResponse.json()).find(
    (section: { section_id: string }) => section.section_id === 'history',
  )
  expect(history.status).toBe('needs_review')
  expect(history.text).toBe(SAVED_SECTION_TEXT)
})
