import { expect, test } from '@playwright/test'
import {
  OFFLINE_MESSAGE,
  SAVE_FAILURE_MESSAGE,
  SERVICE_NOT_RUNNING_MESSAGE,
} from '../src/copy'
import { openSyntheticWorkspace } from './workspace-helpers'

// PT-14 (GROK-44, R1-AC3 + R16): Q5 offline and save-failure copy, the
// service-not-running message, and editor text kept after a failed save.
// Synthetic data only. The Playwright webServer still uses FakeTransport.

test('service not running: plain-language message when the workspace cannot be reached', async ({ page }) => {
  await page.route('**/api/health', (route) => route.abort())
  await page.route('**/api/templates', (route) => route.abort())
  await page.route('**/api/workspaces', (route) => route.abort())
  await page.goto('/')
  await expect(page.getByRole('alert').filter({ hasText: SERVICE_NOT_RUNNING_MESSAGE })).toBeVisible()
  await expect(page.getByRole('status').filter({ hasText: 'Not running' })).toBeVisible()
  await expect(page.getByText(/psychtool init|PSYCHTOOL_WORKSPACES_DIR|Working directory/i)).toHaveCount(0)
})

test('offline: Q5 copy appears and existing editor text stays', async ({ page }) => {
  await openSyntheticWorkspace(page)
  const marker = 'Synthetic offline preservation sentence about a timed reading exercise.'
  const editor = page.getByLabel('Section text')
  await editor.fill(marker)
  await expect(editor).toHaveValue(marker)

  await page.context().setOffline(true)
  await expect(page.getByRole('alert').filter({ hasText: OFFLINE_MESSAGE })).toBeVisible()
  await expect(page.getByLabel('Section text')).toHaveValue(marker)
})

test('save failure: Q5 copy appears and the editor text is still there', async ({ page }) => {
  await openSyntheticWorkspace(page)
  const marker = 'Synthetic save-failure preservation sentence about a timed reading exercise.'
  const editor = page.getByLabel('Section text')
  await editor.fill(marker)
  await expect(page.getByTestId('save-state')).toHaveText('Unsaved changes')

  await page.route('**/api/workspaces/**/sections/**', async (route) => {
    if (route.request().method() === 'PUT') {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'internal error' }),
      })
      return
    }
    await route.continue()
  })

  await page.getByRole('button', { name: 'Save section' }).click()
  await expect(page.getByRole('alert').filter({ hasText: SAVE_FAILURE_MESSAGE })).toBeVisible()
  await expect(page.getByLabel('Section text')).toHaveValue(marker)
  await expect(page.getByTestId('save-state')).toHaveText('Unsaved changes')
})
