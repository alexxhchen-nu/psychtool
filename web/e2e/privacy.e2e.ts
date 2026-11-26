import { expect, test } from '@playwright/test'

const BANNER =
  'Please note: This prototype is not HIPAA compliant yet. Do not enter real patient information. Use only synthetic or separately approved practice materials.'

test('R15: privacy banner stays visible on work, upload and paste surfaces; UI does not claim HIPAA compliance', async ({ page }) => {
  await page.goto('/')
  const banner = page.getByText(BANNER)
  await expect(banner).toBeVisible()

  const caseId = `e2e-r15-${Date.now()}`
  await page.getByLabel('New case ID').fill(caseId)
  await page.getByRole('button', { name: 'Create case' }).click()
  await expect(page.getByRole('combobox', { name: 'Case', exact: true })).toHaveValue(caseId)
  await expect(banner).toBeVisible()

  await page.getByRole('button', { name: 'Paste synthetic text' }).click()
  await expect(page.locator('.paste-panel')).toBeVisible()
  await expect(banner).toBeVisible()

  await page.getByRole('button', { name: 'Upload material' }).click()
  await expect(page.locator('.upload-panel')).toBeVisible()
  await expect(banner).toBeVisible()

  const body = await page.locator('body').innerText()
  expect(body).toContain(BANNER)
  expect(body).not.toMatch(/is HIPAA compliant/i)
  expect(body).not.toMatch(/meets HIPAA/i)
  expect(body).not.toContain('符合 HIPAA')
  expect(body).not.toContain('已保护全部患者隐私')
  expect(body).not.toContain('已保護全部患者隱私')
})
