import { afterEach, describe, expect, test } from 'bun:test'
import { apiRequest, resetSessionTokenCache, sessionToken } from '../src/api'

/** Minimal DOM/fetch stubs: api.ts only touches document.querySelector and fetch. */

type FetchCall = { url: string; init?: RequestInit }

function installDom(metaContent: string | null) {
  const originalDocument = (globalThis as { document?: unknown }).document
  const meta = metaContent === null ? null : { content: metaContent }
  ;(globalThis as { document?: unknown }).document = {
    querySelector(selector: string) {
      return selector === 'meta[name="psychtool-session"]' ? meta : null
    },
  }
  return () => {
    if (originalDocument === undefined) delete (globalThis as { document?: unknown }).document
    else (globalThis as { document?: unknown }).document = originalDocument
  }
}

function installFetch(status = 200, body: unknown = { ok: true }) {
  const calls: FetchCall[] = []
  const originalFetch = globalThis.fetch
  globalThis.fetch = (async (url: unknown, init?: RequestInit) => {
    calls.push({ url: String(url), init })
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    } as Response
  }) as typeof fetch
  return {
    calls,
    restore() { globalThis.fetch = originalFetch },
  }
}

const TOKEN = 'session-token-value-0123456789abcdef'

describe('session token from the served meta tag', () => {
  let restoreDom: (() => void) | null = null
  let fetchStub: ReturnType<typeof installFetch> | null = null

  afterEach(() => {
    restoreDom?.()
    fetchStub?.restore()
    restoreDom = null
    fetchStub = null
    resetSessionTokenCache()
  })

  test('apiRequest attaches X-Psychtool-Token from the meta tag', async () => {
    restoreDom = installDom(TOKEN)
    fetchStub = installFetch()
    resetSessionTokenCache()

    await apiRequest('/api/workspaces')

    expect(fetchStub.calls.length).toBe(1)
    const headers = new Headers(fetchStub.calls[0].init?.headers)
    expect(headers.get('X-Psychtool-Token')).toBe(TOKEN)
  })

  test('existing headers are preserved when the token is added', async () => {
    restoreDom = installDom(TOKEN)
    fetchStub = installFetch()
    resetSessionTokenCache()

    await apiRequest('/api/x', { method: 'POST', headers: { 'Content-Type': 'application/json' } })

    const headers = new Headers(fetchStub.calls[0].init?.headers)
    expect(headers.get('Content-Type')).toBe('application/json')
    expect(headers.get('X-Psychtool-Token')).toBe(TOKEN)
  })

  test('the token is read once and cached', () => {
    restoreDom = installDom(TOKEN)
    resetSessionTokenCache()
    expect(sessionToken()).toBe(TOKEN)
    // Changing the DOM after the first read must not change the token.
    restoreDom()
    restoreDom = installDom('other-token')
    expect(sessionToken()).toBe(TOKEN)
  })

  test('without a meta tag no token header is sent', async () => {
    restoreDom = installDom(null)
    fetchStub = installFetch()
    resetSessionTokenCache()

    expect(sessionToken()).toBeNull()
    await apiRequest('/api/workspaces')

    const headers = new Headers(fetchStub.calls[0].init?.headers)
    expect(headers.get('X-Psychtool-Token')).toBeNull()
  })

  test('resetSessionTokenCache re-reads the DOM', () => {
    restoreDom = installDom(TOKEN)
    resetSessionTokenCache()
    expect(sessionToken()).toBe(TOKEN)
    restoreDom()
    restoreDom = installDom('second-token')
    resetSessionTokenCache()
    expect(sessionToken()).toBe('second-token')
  })

  test('a whitespace-only meta content counts as no token', () => {
    restoreDom = installDom('   ')
    resetSessionTokenCache()
    expect(sessionToken()).toBeNull()
  })
})
