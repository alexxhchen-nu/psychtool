import { expect, test } from '@playwright/test'

// PT-04 browser check against the real backend (webServer in
// playwright.config.ts): R2-AC1 (.txt/.md upload with versioning and
// evidence suggestions), R2-AC2 (typed rejections leave the case unchanged),
// R2-AC3 (first-upload synthetic confirmation gates the form) and R12
// (scans/images get a fixed plain explanation; no OCR on the server).
//
// Prerequisite: build the SPA first (`cd web && bun run build`) so FastAPI
// can serve web/dist. The server runs the offline FakeTransport by default.

const SYNTHETIC_MD =
  '# Synthetic practice note\n\nThe fictional student completed a timed reading exercise.\n\nThe fictional student described the exercise as easy.\n'

const R12_MESSAGE =
  'Scanned PDFs and images are not supported in this version. Upload a .txt or .md file.'

test('upload: R2-AC3 confirmation gate, R2-AC1 .md upload + suggestions, R12 pdf explanation, R2-AC2 unchanged case', async ({ page }) => {
  await page.goto('/')

  // Create a fresh case; the file form must start gated (R2-AC3).
  const caseId = `e2e-upload-${Date.now()}`
  await page.getByLabel('New case ID').fill(caseId)
  await page.getByRole('button', { name: 'Create case' }).click()
  await expect(page.getByRole('combobox', { name: 'Case', exact: true })).toHaveValue(caseId)

  await page.getByRole('button', { name: 'Upload material' }).click()
  const upload = page.locator('.upload-panel')
  const fileInput = upload.getByLabel(/File \(required\)/)

  // R2-AC3: the synthetic-only notice is visible and the input is disabled.
  await expect(upload.getByText(/Before the first upload, confirm/)).toBeVisible()
  await expect(fileInput).toBeDisabled()

  // Tick + confirm: the notice goes away and the input is enabled.
  await upload
    .getByRole('checkbox', { name: /only synthetic or separately approved materials/ })
    .check()
  await upload.getByRole('button', { name: 'Confirm and enable upload' }).click()
  await expect(upload.getByText(/Before the first upload, confirm/)).toBeHidden()
  await expect(fileInput).toBeEnabled()

  // R2-AC1: upload an in-memory synthetic .md file.
  await fileInput.setInputFiles({
    name: 'e2e-note.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from(SYNTHETIC_MD, 'utf-8'),
  })
  await upload.getByLabel(/Anonymous material ID/).fill('e2e-upload-material')
  await upload.getByLabel('Title (required)').fill('E2E uploaded note')
  await upload.getByLabel('Provider (required)').fill('synthetic author')
  await upload.getByLabel('Date (required)').fill('2026-11-24')
  await upload.getByRole('button', { name: 'Upload material' }).click()
  await expect(upload.getByText('Material uploaded')).toBeVisible()
  await expect(page.locator('.case-meta')).toContainText('1 materials')

  // Evidence suggestions can be produced from the uploaded material.
  await upload.getByRole('button', { name: 'Review intake claims' }).click()
  const intake = page.locator('.intake-panel')
  await expect(intake.getByLabel('Material')).toHaveValue('e2e-upload-material')
  await intake.getByRole('button', { name: 'Create candidates' }).click()
  await expect(intake.locator('.intake-card').first()).toBeVisible()

  // R12: a .pdf selection shows the fixed explanation and the case does not grow.
  await page.getByRole('button', { name: 'Upload material' }).click()
  await fileInput.setInputFiles({
    name: 'scan.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 synthetic-not-a-real-scan', 'utf-8'),
  })
  await upload.getByLabel(/Anonymous material ID/).fill('e2e-scan')
  await upload.getByLabel('Title (required)').fill('E2E scan')
  await upload.getByLabel('Provider (required)').fill('synthetic author')
  await upload.getByLabel('Date (required)').fill('2026-11-24')
  await upload.getByRole('button', { name: 'Upload material' }).click()
  await expect(upload.getByText(R12_MESSAGE)).toBeVisible()
  await expect(page.locator('.case-meta')).toContainText('1 materials')

  // R2-AC2 / R12 on the server too (bypassing the browser-side check): the
  // API refuses the scan with the fixed reason and writes nothing.
  const token = await page.locator('meta[name="psychtool-session"]').getAttribute('content')
  const headers = { 'X-Psychtool-Token': token ?? '' }
  const rejected = await page.request.post(`/api/workspaces/${caseId}/materials`, {
    headers,
    multipart: {
      file: { name: 'scan.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 synthetic', 'utf-8') },
      material_id: 'e2e-scan', title: 'scan', provider: 'synthetic', date: '2026-11-24',
    },
  })
  expect(rejected.status()).toBe(400)
  expect(await rejected.json()).toEqual({ detail: R12_MESSAGE, reason: 'scan_not_supported' })
  const materials = await page.request.get(`/api/workspaces/${caseId}/materials`, { headers })
  expect((await materials.json()).length).toBe(1)
})
