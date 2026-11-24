import { expect, test } from '@playwright/test'

// PT-03 security baseline against the real backend serving the built SPA
// (webServer in playwright.config.ts). The backend runs the offline
// FakeTransport by default, so no API key or network access is needed.
//
// Prerequisite: build the SPA first (`cd web && bun run build`).

const EXPECTED_CSP_DIRECTIVES = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self' data:",
  "connect-src 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
  "base-uri 'none'",
  "form-action 'self'",
]

test('security: CSP header on the page, no CSP console errors, API needs the token', async ({ page }) => {
  // The built index.html contains no inline scripts or styles, so the strict
  // CSP must load the app without a single console violation.
  const cspViolations: string[] = []
  page.on('console', (message) => {
    const text = message.text().toLowerCase()
    if (text.includes('content security policy') || text.includes('csp') || text.includes('violat')) {
      cspViolations.push(message.text())
    }
  })

  const response = await page.goto('/')
  expect(response).not.toBeNull()

  // 1. The page response carries the strict CSP and hardening headers.
  const headers = response!.headers()
  const csp = headers['content-security-policy']
  expect(csp).toBeTruthy()
  for (const directive of EXPECTED_CSP_DIRECTIVES) {
    expect(csp).toContain(directive)
  }
  expect(headers['x-content-type-options']).toBe('nosniff')
  expect(headers['referrer-policy']).toBe('no-referrer')
  expect(headers['x-frame-options']).toBe('DENY')
  expect(headers['cache-control']).toBe('no-store')

  // The served index carries the per-start session token meta tag; api.ts
  // reads it and attaches X-Psychtool-Token to every API call.
  const meta = page.locator('meta[name="psychtool-session"]')
  const token = await meta.getAttribute('content')
  expect(token).toBeTruthy()

  // 2. The app loads and creates a case over the token-authenticated API.
  const caseId = `e2e-sec-${Date.now()}`
  await page.getByLabel('New case ID').fill(caseId)
  await page.getByRole('button', { name: 'Create case' }).click()
  await expect(page.getByRole('combobox', { name: 'Case', exact: true })).toHaveValue(caseId)

  // 3. A request without the token is refused: page.request sends no
  // X-Psychtool-Token header of its own.
  const unauthorized = await page.request.get('/api/workspaces')
  expect(unauthorized.status()).toBe(401)

  // 4. No CSP violation was logged while loading and creating the case.
  expect(cspViolations).toEqual([])
})
