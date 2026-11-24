import { expect, test } from '@playwright/test'

// PT-05 browser check against the real backend: R13-AC1 — a paragraph that
// matches the protected-content screen (a norm table) is held back before
// storage, the UI shows the fixed held-back notice, no release/override
// action exists, and the blocked text is not retrievable through the API.
//
// Prerequisite: build the SPA first (`cd web && bun run build`) so FastAPI
// can serve web/dist. The server runs the offline FakeTransport by default.

const MIXED_MD =
  'Teacher reports normal attention in class.\n\n'
  + 'Norm table: raw 12 = T 55.\n\n'
  + 'Parent notes homework takes longer since September.\n'

test('R13-AC1 norm table paragraph is held back', async ({ page }) => {
  await page.goto('/')

  // Fresh case, confirm the synthetic-only notice (same flow as upload.e2e).
  const caseId = `e2e-r13-${Date.now()}`
  await page.getByLabel('New case ID').fill(caseId)
  await page.getByRole('button', { name: 'Create case' }).click()
  await expect(page.getByRole('combobox', { name: 'Case', exact: true })).toHaveValue(caseId)

  await page.getByRole('button', { name: 'Upload material' }).click()
  const upload = page.locator('.upload-panel')
  await upload
    .getByRole('checkbox', { name: /only synthetic or separately approved materials/ })
    .check()
  await upload.getByRole('button', { name: 'Confirm and enable upload' }).click()

  // Upload an in-memory .md whose middle paragraph is a fake norm table.
  await upload.getByLabel(/File \(required\)/).setInputFiles({
    name: 'notes.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from(MIXED_MD, 'utf-8'),
  })
  await upload.getByLabel(/Anonymous material ID/).fill('e2e-r13-material')
  await upload.getByLabel('Title (required)').fill('E2E R13 note')
  await upload.getByLabel('Provider (required)').fill('synthetic author')
  await upload.getByLabel('Date (required)').fill('2026-11-24')
  await upload.getByRole('button', { name: 'Upload material' }).click()

  // The held-back notice appears; the material itself was stored.
  const notice = page.getByTestId('held-back-notice')
  await expect(notice).toBeVisible()
  await expect(notice).toContainText('1 paragraph held back')
  await expect(upload.getByText('Material uploaded')).toBeVisible()

  // M1 has no release path: nothing on the page offers release/override.
  await expect(page.getByRole('button', { name: /release|override|unblock/i })).toHaveCount(0)

  // Through the API: the stored passages contain the normal paragraphs but
  // never the held-back norm table text.
  const token = await page.locator('meta[name="psychtool-session"]').getAttribute('content')
  const headers = { 'X-Psychtool-Token': token ?? '' }
  const materials = await page.request.get(`/api/workspaces/${caseId}/materials`, { headers })
  expect(materials.status()).toBe(200)
  const stored = (await materials.json()) as {
    id: string
    passages: { id: string; text: string }[]
  }[]
  const material = stored.find((entry) => entry.id === 'e2e-r13-material')
  expect(material).toBeDefined()
  const allText = material!.passages.map((passage) => passage.text).join('\n')
  expect(allText).toContain('normal attention')
  expect(allText).toContain('homework takes longer')
  expect(allText).not.toContain('Norm table')
  expect(material!.passages).toHaveLength(2)
})
