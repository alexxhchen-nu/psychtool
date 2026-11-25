import { afterEach, describe, expect, test } from 'bun:test'
import { getDimensions, setEvidenceDimension, uploadMaterialWithKind } from '../src/api'
import { resetSessionTokenCache } from '../src/api'
import type { DimensionsResponse } from '../src/types'

/** Minimal DOM/fetch stubs: api.ts only touches document.querySelector and fetch. */

type FetchCall = { url: string; init?: RequestInit }

function installDom() {
  const originalDocument = (globalThis as { document?: unknown }).document
  ;(globalThis as { document?: unknown }).document = {
    querySelector() { return null },
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

const DIMENSIONS_BODY: DimensionsResponse = {
  has_list: true,
  list: { material_id: 'dims-list', title: 'Working list', version: 1 },
  dimensions: [
    { id: 'dim_a', name: 'Attention', passage_id: 'p1', paragraph: 1, start: 13, end: 22, quote_text_of_passage_span: 'Attention' },
  ],
  held_back: 1,
  disclaimer: 'This is not a diagnosis. The diagnosis is yours.',
  needs_review_count: 2,
  items: [],
}

describe('dimension API client', () => {
  let restoreDom: (() => void) | null = null
  let fetchStub: ReturnType<typeof installFetch> | null = null

  afterEach(() => {
    restoreDom?.()
    fetchStub?.restore()
    restoreDom = null
    fetchStub = null
    resetSessionTokenCache()
  })

  test('getDimensions hits the read-only route', async () => {
    restoreDom = installDom()
    fetchStub = installFetch(200, DIMENSIONS_BODY)
    const result = await getDimensions('case-a')
    expect(result.disclaimer).toBe('This is not a diagnosis. The diagnosis is yours.')
    expect(result.dimensions[0].quote_text_of_passage_span).toBe('Attention')
    expect(fetchStub.calls[0].url).toBe('/api/workspaces/case-a/dimensions')
    expect(fetchStub.calls[0].init?.method).toBeUndefined()
  })

  test('setEvidenceDimension sends exactly the chosen body', async () => {
    restoreDom = installDom()
    fetchStub = installFetch(200, { id: 'ev_1' })
    await setEvidenceDimension('case-a', 'ev_1', { action: 'confirm' })
    await setEvidenceDimension('case-a', 'ev_1', { dimension_id: 'dim_a' })
    await setEvidenceDimension('case-a', 'ev_1', { action: 'none' })
    await setEvidenceDimension('case-a', 'ev_1', { action: 'reset' })
    const calls = fetchStub.calls
    expect(calls[0].url).toBe('/api/workspaces/case-a/evidence/ev_1/dimension')
    expect(calls.every((call) => call.init?.method === 'PUT')).toBe(true)
    expect(calls.map((call) => JSON.parse(String(call.init?.body)))).toEqual([
      { action: 'confirm' },
      { dimension_id: 'dim_a' },
      { action: 'none' },
      { action: 'reset' },
    ])
  })

  test('uploadMaterialWithKind appends kind=dims for dims uploads only', async () => {
    restoreDom = installDom()
    fetchStub = installFetch(200, { ok: true })
    const dimsForm = new FormData()
    dimsForm.append('file', new Blob(['x']))
    await uploadMaterialWithKind('case-a', dimsForm, 'dims')
    const caseForm = new FormData()
    caseForm.append('file', new Blob(['x']))
    await uploadMaterialWithKind('case-a', caseForm, 'case')
    const sent = async (call: FetchCall) =>
      (call.init?.body as FormData).get('kind')
    expect(await sent(fetchStub.calls[0])).toBe('dims')
    expect(await sent(fetchStub.calls[1])).toBeNull()
  })
})
