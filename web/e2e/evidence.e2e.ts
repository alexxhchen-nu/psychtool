import { expect, test } from '@playwright/test'

// PT-06 (GROK-36) browser check against the real backend: R4 — evidence is
// for the clinician's review, not a conclusion. R4-AC1: every evidence item
// carries the verbatim quote plus its material, version and paragraph /
// character range. R4-AC2: clicking an item scrolls to and highlights the
// exact source text. R4-AC3: conflicting accounts of the same thing in
// different materials are both kept, never merged.
//
// Prerequisite: build the SPA first (`cd web && bun run build`) so FastAPI
// can serve web/dist. The server runs the offline FakeTransport by default.

const CAREGIVER_MD =
  'Mother says he sleeps about 8 hours a night and keeps a regular routine.\n\n'
  + 'He walks to school with a neighbour.\n'

const SELF_MD =
  'I often stay on my phone until about 1 a.m. before falling asleep.\n'

const SLEEP_QUOTE =
  'Mother says he sleeps about 8 hours a night and keeps a regular routine'

// Code-point-safe slice, matching the Python span contract (ADR 0014).
function codePointSlice(text: string, start: number, end: number): string {
  return Array.from(text).slice(start, end).join('')
}

test('R4-AC1 R4-AC2 R4-AC3 evidence items list quote, material, version, paragraph and range; click highlights; both accounts kept', async ({ page }) => {
  await page.goto('/')

  const caseId = `e2e-r4-${Date.now()}`
  await page.getByLabel('New case ID').fill(caseId)
  await page.getByRole('button', { name: 'Create case' }).click()
  await expect(page.getByRole('combobox', { name: 'Case', exact: true })).toHaveValue(caseId)

  await page.getByRole('button', { name: 'Upload material' }).click()
  const upload = page.locator('.upload-panel')
  await upload
    .getByRole('checkbox', { name: /only synthetic or separately approved materials/ })
    .check()
  await upload.getByRole('button', { name: 'Confirm and enable upload' }).click()

  // Two materials with conflicting accounts of the same thing (sleep).
  await upload.getByLabel(/File \(required\)/).setInputFiles({
    name: 'caregiver.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from(CAREGIVER_MD, 'utf-8'),
  })
  await upload.getByLabel(/Anonymous material ID/).fill('caregiver')
  await upload.getByLabel('Title (required)').fill('Caregiver note')
  await upload.getByLabel('Provider (required)').fill('synthetic author')
  await upload.getByLabel('Date (required)').fill('2026-11-24')
  await upload.getByRole('button', { name: 'Upload material' }).click()
  await expect(upload.getByText('Material uploaded')).toBeVisible()

  await upload.getByLabel(/File \(required\)/).setInputFiles({
    name: 'self.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from(SELF_MD, 'utf-8'),
  })
  await upload.getByLabel(/Anonymous material ID/).fill('self')
  await upload.getByLabel('Title (required)').fill('Self report')
  await upload.getByLabel('Provider (required)').fill('synthetic author')
  await upload.getByLabel('Date (required)').fill('2026-11-24')
  await upload.getByRole('button', { name: 'Upload material' }).click()
  await expect(upload.getByText('Material uploaded')).toBeVisible()

  // R4-AC1: the Evidence view lists the items with source metadata.
  await page.getByRole('button', { name: 'Evidence' }).click()
  const items = page.getByTestId('evidence-item')
  await expect(items).toHaveCount(3)
  const sleepItem = items.filter({ hasText: SLEEP_QUOTE })
  await expect(sleepItem).toContainText('Caregiver note · version 1 · paragraph 1')

  // Via the API: every item's quote is verbatim equal to the stored
  // passage slice at [start:end), and material fields are present.
  const token = await page.locator('meta[name="psychtool-session"]').getAttribute('content')
  const headers = { 'X-Psychtool-Token': token ?? '' }
  const evidence = await (
    await page.request.get(`/api/workspaces/${caseId}/evidence`, { headers })
  ).json() as {
    extractor: string
    items: {
      id: string
      quote: string
      material_id: string
      material_title: string
      material_version: number
      passage_id: string
      paragraph: number
      start: number
      end: number
    }[]
    dropped: number
  }
  expect(evidence.extractor).toBe('rule')
  expect(evidence.dropped).toBe(0)
  const materials = (await (
    await page.request.get(`/api/workspaces/${caseId}/materials`, { headers })
  ).json()) as { id: string; passages: { id: string; text: string }[] }[]
  for (const item of evidence.items) {
    const material = materials.find((entry) => entry.id === item.material_id)
    expect(material).toBeDefined()
    const passage = material!.passages.find((entry) => entry.id === item.passage_id)
    expect(passage).toBeDefined()
    expect(codePointSlice(passage!.text, item.start, item.end)).toBe(item.quote)
    expect(item.material_title.length).toBeGreaterThan(0)
    expect(item.material_version).toBe(1)
    expect(item.paragraph).toBeGreaterThanOrEqual(1)
  }

  // R4-AC2: clicking the item highlights the exact source text in view.
  await sleepItem.click()
  const highlight = page.getByTestId('evidence-highlight')
  await expect(highlight).toBeVisible()
  await expect(highlight).toHaveText(SLEEP_QUOTE)
  await expect(highlight).toBeInViewport()
  await expect(page.getByTestId('evidence-source')).toContainText(
    'He walks to school with a neighbour.',
  )

  // R4-AC3: both sleep accounts are listed as separate items with their own
  // material titles; they are never merged into one statement.
  const selfItem = items.filter({
    hasText: 'I often stay on my phone until about 1 a.m. before falling asleep',
  })
  await expect(selfItem).toHaveCount(1)
  await expect(selfItem).toContainText('Self report · version 1 · paragraph 1')
  await expect(sleepItem).toHaveCount(1)
})

test('R4-AC2 click scrolls the source paragraph into view and highlights the exact quote', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  await page.goto('/')
  const caseId = `e2e-r4-scroll-${Date.now()}`
  await page.getByLabel('New case ID').fill(caseId)
  await page.getByRole('button', { name: 'Create case' }).click()
  await expect(page.getByRole('combobox', { name: 'Case', exact: true })).toHaveValue(caseId)
  await page.getByRole('button', { name: 'Upload material' }).click()
  const upload = page.locator('.upload-panel')
  await upload
    .getByRole('checkbox', { name: /only synthetic or separately approved materials/ })
    .check()
  await upload.getByRole('button', { name: 'Confirm and enable upload' }).click()
  const filler = Array.from({ length: 40 }, (_, i) => `Filler paragraph ${i + 1} about the weekly timetable`).join('\n\n')
  const target = 'Last paragraph says he walks the dog every evening'
  await upload.getByLabel(/File \(required\)/).setInputFiles({
    name: 'long.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from(`${target}.\n\n${filler}\n`, 'utf-8'),
  })
  await upload.getByLabel(/Anonymous material ID/).fill('long')
  await upload.getByLabel('Title (required)').fill('Long note')
  await upload.getByLabel('Provider (required)').fill('synthetic author')
  await upload.getByLabel('Date (required)').fill('2026-11-24')
  await upload.getByRole('button', { name: 'Upload material' }).click()
  await expect(upload.getByText('Material uploaded')).toBeVisible()
  await page.getByRole('button', { name: 'Evidence' }).click()
  const item = page.getByTestId('evidence-item').filter({ hasText: target })
  await expect(item).toContainText('Long note · version 1 · paragraph 1')
  await item.click()
  const highlight = page.getByTestId('evidence-highlight')
  await expect(highlight).toHaveText(target)
  await expect(highlight).toBeInViewport()
  // The clicked item sits at the top of a 41-item list; the source pane
  // starts below the list, so the highlight is only visible if it scrolled.
  await expect(item).not.toBeInViewport()
})
