import { expect, test } from '@playwright/test'

// PT-08 (GROK-38) browser check against the real backend: R7 — dimensions
// come only from her uploaded list, unsure mappings stay "Needs review",
// every view carries the fixed not-diagnosis disclaimer, and her choices
// (confirm / change / wrong-no-dimension) persist without re-upload.
//
// Prerequisite: build the SPA first (`cd web && bun run build`) so FastAPI
// can serve web/dist. The server runs the offline FakeTransport by default.

const LIST_TITLE = 'DSM-5 dimension working list (your upload, synthetic)'

const DIMENSION_LIST =
  'This is a clinician-made working list of dimension names for filing evidence. It is not the text of any diagnostic criteria.\n'
  + 'Dimension 1: Sustained attention (staying engaged during ongoing tasks).\n'
  + 'Dimension 2: Working memory and processing speed.\n'
  + 'Dimension 3: Reading and word decoding.\n'
  + 'Dimension 4: Mood and emotion regulation.\n'
  + 'Dimension 5: Sleep and daily routine.\n'
  + 'Dimension 6: Social interaction.'

const LIST_NAMES = [
  'Sustained attention',
  'Working memory and processing speed',
  'Reading and word decoding',
  'Mood and emotion regulation',
  'Sleep and daily routine',
  'Social interaction',
]

// One clear one-hit ("distractible" -> Sustained attention), one ambiguous
// ("reads slowly" + "sleeps" -> Reading and word decoding vs Sleep and daily
// routine), and one unmatched sentence.
const CASE_MD =
  'He is distractible and loses focus during homework every afternoon.\n\n'
  + 'He reads slowly at bedtime and sleeps badly on school nights.\n\n'
  + 'He rides his bike to the park after school.\n'

const ONE_HIT_QUOTE = 'He is distractible and loses focus during homework every afternoon'
const AMBIGUOUS_QUOTE = 'He reads slowly at bedtime and sleeps badly on school nights'
const UNMATCHED_QUOTE = 'He rides his bike to the park after school'

const BLOCKED_PHRASES = [
  'meets criteria',
  'consistent with a diagnosis of',
  'diagnosis is',
  'suggests a diagnosis',
  'diagnosed with',
  'criteria for',
]

async function sessionHeaders(page: import('@playwright/test').Page) {
  const token = await page.locator('meta[name="psychtool-session"]').getAttribute('content')
  return { 'X-Psychtool-Token': token ?? '' }
}

async function setupCase(page: import('@playwright/test').Page, prefix: string, withList: boolean) {
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
  // Wait until the confirmation POST has landed. The API material uploads
  // below would 403 if they raced the confirmation (push CI flake on AC5).
  await expect(upload.getByText(/Before the first upload, confirm/)).toBeHidden()

  const headers = await sessionHeaders(page)
  const caseResponse = await page.request.post(
    `/api/workspaces/${caseId}/materials`,
    {
      headers,
      multipart: {
        file: { name: 'case.md', mimeType: 'text/markdown', buffer: Buffer.from(CASE_MD, 'utf-8') },
        material_id: 'case-note',
        title: 'Caregiver note',
        provider: 'synthetic author',
        date: '2026-11-24',
        kind: 'case',
      },
    },
  )
  expect(caseResponse.ok(), await caseResponse.text()).toBe(true)

  if (withList) {
    const listResponse = await page.request.post(
      `/api/workspaces/${caseId}/materials`,
      {
        headers,
        multipart: {
          file: { name: 'dims.md', mimeType: 'text/markdown', buffer: Buffer.from(DIMENSION_LIST, 'utf-8') },
          material_id: 'dims-list',
          title: LIST_TITLE,
          provider: 'synthetic author',
          date: '2026-11-24',
          kind: 'dims',
        },
      },
    )
    expect(listResponse.ok(), await listResponse.text()).toBe(true)
  }
  // The uploads above bypassed the UI, so reload to refresh the App's
  // material state before opening the panels. Reload restores the first
  // case in the picker (see case-switch / categories e2e), so re-select.
  await page.reload()
  const picker = page.getByRole('combobox', { name: 'Case', exact: true })
  await picker.selectOption(caseId)
  await expect(picker).toHaveValue(caseId)
  return caseId
}

test('R7-AC1 R7-AC6 dimension group headers equal her list names only, with the disclaimer and no diagnosis language', async ({ page }) => {
  const caseId = await setupCase(page, 'e2e-r7-ac1', true)

  await page.getByRole('button', { name: 'Dimensions' }).click()
  const panel = page.locator('.dimensions-panel')
  await expect(panel.getByTestId('not-diagnosis')).toBeVisible()

  // Group headers are exactly her six names.
  const headers = panel.locator('.dimension-group-header strong')
  await expect(headers).toHaveCount(7) // six + "Not mapped or unsure"
  const headerTexts = await headers.allTextContents()
  for (const name of LIST_NAMES) {
    expect(headerTexts).toContain(name)
  }
  expect(headerTexts).toContain('Not mapped or unsure')
  // No built-in name leaks in.
  expect(headerTexts.join(' ')).not.toContain('ADHD')
  expect(headerTexts.join(' ')).not.toContain('Hyperactivity')

  // R7-AC6: page text carries none of the blocked phrases, and the required
  // disclaimer itself is present verbatim.
  const disclaimer = panel.getByTestId('not-diagnosis')
  await expect(disclaimer).toContainText(
    'Dimension mapping only helps organize evidence. This is not a diagnosis. The diagnosis is yours.',
  )
  const bodyText = (await panel.innerText()).toLowerCase()
  for (const phrase of BLOCKED_PHRASES) {
    // The disclaimer itself legitimately contains "diagnosis is".
    if (phrase === 'diagnosis is') continue
    expect(bodyText).not.toContain(phrase)
  }

  await panel.screenshot({ path: 'test-results/dimensions-page.png' })
})

test('R7-AC2 a case without a list shows the empty state and no mapped chips', async ({ page }) => {
  await setupCase(page, 'e2e-r7-ac2', false)

  await page.getByRole('button', { name: 'Dimensions' }).click()
  const panel = page.locator('.dimensions-panel')
  await expect(panel).toContainText(
    'No dimension list has been uploaded for this case, so no evidence gets a dimension.',
  )
  await expect(panel).toContainText(
    'Upload your own dimension list or an approved excerpt to see dimension mapping.',
  )
  await expect(panel.getByRole('button', { name: 'Upload dimension list' })).toBeVisible()
  await expect(panel.getByTestId('not-diagnosis')).toBeVisible()

  // Every evidence chip in the Evidence view is "No dimension" — nothing
  // was guessed from built-in knowledge.
  await page.getByRole('button', { name: 'Evidence' }).click()
  const chips = page.getByTestId('dimension-chip')
  await expect(chips.first()).toBeVisible()
  const count = await chips.count()
  expect(count).toBeGreaterThan(0)
  for (let i = 0; i < count; i += 1) {
    await expect(chips.nth(i)).toHaveText('Dimension: No dimension')
  }
})

test('R7-AC3 reason quotes visible text and clicks highlight the evidence and list sources', async ({ page }) => {
  await setupCase(page, 'e2e-r7-ac3', true)

  await page.getByRole('button', { name: 'Dimensions' }).click()
  const panel = page.locator('.dimensions-panel')

  const row = panel.getByTestId('dimension-item').filter({ hasText: ONE_HIT_QUOTE })
  await expect(row).toHaveCount(1)
  await expect(row.getByTestId('dimension-chip')).toHaveText(
    'Sustained attention · Needs review',
  )
  const reason = await row.getByTestId('dimension-reason').textContent()
  expect((reason ?? '').startsWith('Why: ')).toBe(true)
  const quoted = (reason ?? '').match(/“(.+?)”/)
  expect(quoted).not.toBeNull()
  expect(ONE_HIT_QUOTE).toContain(quoted![1])

  // Clicking the row highlights the evidence's source span.
  await row.getByRole('button').first().click()
  const sourceHighlight = panel.getByTestId('dimension-source-highlight')
  await expect(sourceHighlight).toBeVisible()
  const markText = await sourceHighlight.textContent()
  expect(ONE_HIT_QUOTE).toContain(markText ?? '')

  // "Source: your list, paragraph n" highlights the list line.
  const attentionGroup = panel.getByTestId('dimension-group').first()
  await attentionGroup.getByRole('button', { name: /Source: your list, paragraph/ }).click()
  const listHighlight = panel.getByTestId('dimension-list-highlight')
  await expect(listHighlight).toBeVisible()
  await expect(listHighlight).toHaveText('Sustained attention')
  await expect(panel.getByTestId('dimension-list-source')).toContainText(
    `${LIST_TITLE} · version 1 · paragraph 2`,
  )
})

test('R7-AC4 Change to… assigns the new dimension, marks Confirmed by you, and survives reload', async ({ page }) => {
  const caseId = await setupCase(page, 'e2e-r7-ac4', true)

  await page.getByRole('button', { name: 'Dimensions' }).click()
  const panel = page.locator('.dimensions-panel')

  const row = panel.getByTestId('dimension-item').filter({ hasText: ONE_HIT_QUOTE })
  await row.getByLabel('Change dimension').selectOption({ label: 'Sleep and daily routine' })

  await expect(row.getByTestId('dimension-chip')).toHaveText(
    'Sleep and daily routine · Confirmed by you',
  )

  await page.reload()
  await page.getByRole('combobox', { name: 'Case', exact: true }).selectOption(caseId)
  await page.getByRole('button', { name: 'Dimensions' }).click()
  const reloadedRow = page
    .locator('.dimensions-panel')
    .getByTestId('dimension-item')
    .filter({ hasText: ONE_HIT_QUOTE })
  await expect(reloadedRow.getByTestId('dimension-chip')).toHaveText(
    'Sleep and daily routine · Confirmed by you',
  )
})

test('R7-AC5 an ambiguous item shows "Dimension · Needs review" and never a guessed dimension', async ({ page }) => {
  await setupCase(page, 'e2e-r7-ac5', true)

  await page.getByRole('button', { name: 'Dimensions' }).click()
  const panel = page.locator('.dimensions-panel')

  const ambiguous = panel.getByTestId('dimension-item').filter({ hasText: AMBIGUOUS_QUOTE })
  await expect(ambiguous).toHaveCount(1)
  await expect(ambiguous.getByTestId('dimension-chip')).toHaveText('Dimension · Needs review')
  await expect(ambiguous.getByTestId('dimension-reason')).toContainText('cannot tell')

  // The unmatched sentence is plain "No dimension".
  const unmatched = panel.getByTestId('dimension-item').filter({ hasText: UNMATCHED_QUOTE })
  await expect(unmatched.getByTestId('dimension-chip')).toHaveText('No dimension')
})

test('R7 Wrong, no dimension turns the chip into "No dimension"', async ({ page }) => {
  await setupCase(page, 'e2e-r7-none', true)

  await page.getByRole('button', { name: 'Dimensions' }).click()
  const panel = page.locator('.dimensions-panel')

  const row = panel.getByTestId('dimension-item').filter({ hasText: ONE_HIT_QUOTE })
  await row.getByRole('button', { name: 'Wrong, no dimension' }).click()
  await expect(row.getByTestId('dimension-chip')).toHaveText('No dimension')
})
