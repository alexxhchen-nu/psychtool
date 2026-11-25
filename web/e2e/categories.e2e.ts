import { expect, test } from '@playwright/test'

// PT-07 (GROK-37) browser check against the real backend: R5 — every
// evidence item shows one suggested category with a reason that quotes
// visible source text (R5-AC1), undecidable items stay Uncategorized instead
// of being guessed (R5-AC2), provider role is recorded separately from
// category, and her correction survives reload and a rules refresh.
//
// Prerequisite: build the SPA first (`cd web && bun run build`) so FastAPI
// can serve web/dist. The server runs the offline FakeTransport by default.

const SCHOOL_MD =
  'Teacher says he reads slowly in class.\n\nThe weather was cloudy that week.\n'

const TEACHER_QUOTE = 'Teacher says he reads slowly in class'
const WEATHER_QUOTE = 'The weather was cloudy that week'

const UNCATEGORIZED_REASON =
  'No words in the text indicate a category, so the system does not choose for you.'

async function setupCaseWithSchoolNote(page: import('@playwright/test').Page, prefix: string) {
  await page.goto('/')

  const caseId = `${prefix}-${Date.now()}`
  await page.getByLabel('New case ID').fill(caseId)
  await page.getByRole('button', { name: 'Create case' }).click()
  await expect(page.getByRole('combobox', { name: 'Case', exact: true })).toHaveValue(caseId)

  await page.getByRole('button', { name: 'Upload material' }).click()
  const upload = page.locator('.upload-panel')
  await upload
    .getByRole('checkbox', { name: /only synthetic or separately approved materials/ })
    .check()
  await upload.getByRole('button', { name: 'Confirm and enable upload' }).click()

  await upload.getByLabel(/File \(required\)/).setInputFiles({
    name: 'school.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from(SCHOOL_MD, 'utf-8'),
  })
  await upload.getByLabel(/Anonymous material ID/).fill('school')
  await upload.getByLabel('Title (required)').fill('School note')
  await upload.getByLabel('Provider (required)').fill('synthetic author')
  await upload.getByLabel('Date (required)').fill('2026-11-24')
  await upload.getByRole('button', { name: 'Upload material' }).click()
  await expect(upload.getByText('Material uploaded')).toBeVisible()

  await page.getByRole('button', { name: 'Evidence' }).click()
  return caseId
}

test('R5-AC1 categorized item shows category chip, separate role chip and a reason quoting visible source text', async ({ page }) => {
  await setupCaseWithSchoolNote(page, 'e2e-r5-ac1')

  const item = page.getByTestId('evidence-item').filter({ hasText: TEACHER_QUOTE })
  await expect(item).toHaveCount(1)

  await expect(item.getByTestId('category-chip')).toHaveText('Development & school')
  // Role is recorded separately from category.
  await expect(item.getByTestId('role-chip')).toHaveText('From: School')

  const reason = item.getByTestId('category-reason')
  await expect(reason).toBeVisible()
  const reasonText = (await reason.textContent()) ?? ''
  expect(reasonText.startsWith('Why: ')).toBe(true)
  // The reason quotes a verbatim substring of the item's quote — never
  // "based on context" (R5-AC1).
  const match = reasonText.match(/“(.+?)”/)
  expect(match).not.toBeNull()
  expect(TEACHER_QUOTE.includes(match![1])).toBe(true)
})

test('R5-AC2 undecidable item is Uncategorized, not a guess', async ({ page }) => {
  await setupCaseWithSchoolNote(page, 'e2e-r5-ac2')

  const item = page.getByTestId('evidence-item').filter({ hasText: WEATHER_QUOTE })
  await expect(item).toHaveCount(1)

  await expect(item.getByTestId('category-chip')).toHaveText('Uncategorized')
  await expect(item.getByTestId('category-reason')).toHaveText(`Why: ${UNCATEGORIZED_REASON}`)
  // No source keyword either -> the separate role chip asks her to confirm.
  await expect(item.getByTestId('role-chip')).toHaveText('From: To confirm')
})

test('R5 correction persists across reload', async ({ page }) => {
  const caseId = await setupCaseWithSchoolNote(page, 'e2e-r5-correct')

  const weather = page.getByTestId('evidence-item').filter({ hasText: WEATHER_QUOTE })
  await expect(weather.getByTestId('category-chip')).toHaveText('Uncategorized')

  // Her correction: Uncategorized -> Other via the change-category select.
  const listItem = page.locator('li', { has: page.getByTestId('evidence-item').filter({ hasText: WEATHER_QUOTE }) })
  await listItem.getByLabel('Change category').selectOption('other')
  await expect(weather.getByTestId('category-chip')).toHaveText('Other')
  await expect(weather.getByText('Set by you')).toBeVisible()

  // Survives a full page reload.
  await page.reload()
  // A fresh load selects the first case in the list; pick this test's case.
  await page.getByRole('combobox', { name: 'Case', exact: true }).selectOption(caseId)
  await page.getByRole('button', { name: 'Evidence' }).click()
  const weatherAfterReload = page.getByTestId('evidence-item').filter({ hasText: WEATHER_QUOTE })
  await expect(weatherAfterReload.getByTestId('category-chip')).toHaveText('Other')
  await expect(weatherAfterReload.getByText('Set by you')).toBeVisible()

  // Survives a rules refresh (stable location-derived ids; her choice is
  // never overwritten — ADR 0015).
  const token = await page.locator('meta[name="psychtool-session"]').getAttribute('content')
  const refresh = await page.request.post(
    `/api/workspaces/${caseId}/evidence/refresh`,
    { headers: { 'X-Psychtool-Token': token ?? '' } },
  )
  expect(refresh.ok()).toBe(true)

  await page.reload()
  // A fresh load selects the first case in the list; pick this test's case.
  await page.getByRole('combobox', { name: 'Case', exact: true }).selectOption(caseId)
  await page.getByRole('button', { name: 'Evidence' }).click()
  const weatherAfterRefresh = page.getByTestId('evidence-item').filter({ hasText: WEATHER_QUOTE })
  await expect(weatherAfterRefresh.getByTestId('category-chip')).toHaveText('Other')
  await expect(weatherAfterRefresh.getByText('Set by you')).toBeVisible()
})
