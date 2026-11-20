import { describe, expect, test } from 'bun:test'
import {
  approvalInput,
  canPrepare,
  clearStoredRequestId,
  egressReducer,
  initialEgressState,
  readStoredRequestId,
  requestStorageKey,
  storeRequestId,
  validateRecoveredRequest,
} from '../src/egress-state'
import type { EgressState, RequestStorage } from '../src/egress-state'
import type { EgressRequest } from '../src/types'

const request: EgressRequest = {
  request_id: 'egress-1', workspace_id: 'case-a', purpose: 'section_generation',
  data_tier: 'real', provider_base_url: 'http://127.0.0.1:11434/v1', model: 'local-model',
  preview: 'Exact input\n[PERSON_1] reported difficulty.',
  source_refs: [{ kind: 'claim', id: 'claim-1', version: 2 }],
  identifier_categories: ['person'], content_hash: 'a'.repeat(64), status: 'prepared',
  approval_mode: null, reviewer: null, approval_reason: null,
  prepared_at: '2026-11-09T00:00:00Z', approved_at: null, sent_at: null,
  requires_human_review: true,
}
const confirmation = { reviewer: 'Reviewer label', syntheticReason: '', confirmed: true }

function prepared(): EgressState {
  const idle = egressReducer(initialEgressState, { type: 'restored', request: null })
  const preparing = egressReducer(idle, { type: 'prepare', acknowledgeUncertain: false })
  return egressReducer(preparing, { type: 'prepared', request })
}
function approved(): EgressState {
  const approving = egressReducer(prepared(), { type: 'approve', confirmation })
  return egressReducer(approving, { type: 'approved', request: { ...request, status: 'approved' } })
}
function sending(): EgressState {
  return egressReducer(approved(), { type: 'send', storageCleared: true })
}
function memoryStorage(): RequestStorage {
  const values = new Map<string, string>()
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => { values.set(key, value) },
    removeItem: (key) => { values.delete(key) },
  }
}

describe('egress transition gates', () => {
  test('restoration blocks Prepare, Approve and Send until the server lookup finishes', () => {
    expect(canPrepare(initialEgressState, true)).toBe(false)
    expect(egressReducer(initialEgressState, { type: 'prepare', acknowledgeUncertain: true }).phase).toBe('restoring')
    expect(egressReducer(initialEgressState, { type: 'approve', confirmation }).phase).toBe('restoring')
    expect(egressReducer(initialEgressState, { type: 'send', storageCleared: true }).phase).toBe('restoring')
  })

  test('prepared requests cannot send and approval never starts a send', () => {
    expect(egressReducer(prepared(), { type: 'send', storageCleared: true }).phase).toBe('prepared')
    expect(approved().phase).toBe('approved')
    expect(approved().request?.status).toBe('approved')
  })

  test('approval requires an explicit checkbox and a nonempty reviewer', () => {
    expect(egressReducer(prepared(), { type: 'approve', confirmation: { ...confirmation, confirmed: false } }).phase).toBe('prepared')
    expect(egressReducer(prepared(), { type: 'approve', confirmation: { ...confirmation, reviewer: '  ' } }).phase).toBe('prepared')
    expect(approvalInput(request, confirmation)).toEqual({ content_hash: 'a'.repeat(64), reviewer: 'Reviewer label' })
  })

  test('synthetic approval uses only an explicit reason and confirmation, never reviewer', () => {
    const synthetic = { ...request, data_tier: 'synthetic' as const }
    expect(approvalInput(synthetic, confirmation)).toBeNull()
    expect(approvalInput(synthetic, { ...confirmation, syntheticReason: 'Synthetic test fixture', confirmed: false })).toBeNull()
    expect(approvalInput(synthetic, { ...confirmation, syntheticReason: ' Synthetic test fixture ' })).toEqual({
      content_hash: 'a'.repeat(64), synthetic_auto_reason: 'Synthetic test fixture',
    })
  })

  test('400 approval rejection preserves the exact preview for correction', () => {
    const approving = egressReducer(prepared(), { type: 'approve', confirmation })
    const rejected = egressReducer(approving, { type: 'approval_failed', status: 400 })
    expect(rejected.phase).toBe('prepared')
    expect(rejected.request?.preview).toBe('Exact input\n[PERSON_1] reported difficulty.')
    expect(egressReducer(rejected, { type: 'send', storageCleared: true }).phase).toBe('prepared')
  })

  test('a different approval response ID or hash invalidates the review', () => {
    for (const changed of [{ ...request, request_id: 'other' }, { ...request, content_hash: 'b'.repeat(64) }]) {
      const approving = egressReducer(prepared(), { type: 'approve', confirmation })
      expect(egressReducer(approving, { type: 'approved', request: { ...changed, status: 'approved' } }).phase).toBe('invalidated')
    }
  })

  test('send cannot start until session removal has been verified', () => {
    expect(egressReducer(approved(), { type: 'send', storageCleared: false }).phase).toBe('approved')
    expect(sending().phase).toBe('sending')
    expect(egressReducer(sending(), { type: 'send', storageCleared: true }).phase).toBe('sending')
  })

  test('403 keeps approval but never automatically sends again', () => {
    const denied = egressReducer(sending(), { type: 'send_failed', status: 403 })
    expect(denied.phase).toBe('approved')
    expect(denied.request?.status).toBe('approved')
  })

  test('409 invalidates approval and cannot be sent', () => {
    const invalidated = egressReducer(sending(), { type: 'send_failed', status: 409 })
    expect(invalidated.phase).toBe('invalidated')
    expect(egressReducer(invalidated, { type: 'send', storageCleared: true }).phase).toBe('invalidated')
    const approving = egressReducer(prepared(), { type: 'approve', confirmation })
    expect(egressReducer(approving, { type: 'approval_failed', status: 409 }).phase).toBe('invalidated')
  })

  test('422 and uncertain delivery prohibit same-request retries', () => {
    const outcomes = [
      { status: 422, phase: 'output_blocked' },
      { status: 502, phase: 'uncertain_failure' },
      { status: 500, phase: 'uncertain_failure' },
      { status: 0, phase: 'uncertain_failure' },
    ]
    for (const outcome of outcomes) {
      const terminal = egressReducer(sending(), { type: 'send_failed', status: outcome.status })
      expect(terminal.phase).toBe(outcome.phase)
      expect(egressReducer(terminal, { type: 'send', storageCleared: true }).phase).toBe(outcome.phase)
      expect(egressReducer(terminal, { type: 'approve', confirmation }).phase).toBe(outcome.phase)
    }
  })

  test('a new request after uncertain delivery needs explicit new-request intent', () => {
    const uncertain = egressReducer(sending(), { type: 'send_failed', status: 502 })
    expect(canPrepare(uncertain, false)).toBe(false)
    expect(egressReducer(uncertain, { type: 'prepare', acknowledgeUncertain: false }).phase).toBe('uncertain_failure')
    const fresh = egressReducer(uncertain, { type: 'prepare', acknowledgeUncertain: true })
    expect(fresh.phase).toBe('preparing')
    expect(fresh.request).toBeNull()
  })

  test('source changes revoke readiness, and late prepare or approval cannot restore it', () => {
    for (const state of [prepared(), approved(), egressReducer(prepared(), { type: 'approve', confirmation })]) {
      const stale = egressReducer(state, { type: 'invalidate' })
      expect(stale.phase).toBe('invalidated')
      expect(egressReducer(stale, { type: 'approved', request: { ...request, status: 'approved' } }).phase).toBe('invalidated')
      expect(egressReducer(stale, { type: 'prepared', request }).phase).toBe('invalidated')
    }
  })

  test('initial recovery and terminal outcomes are not invalidated by current selections', () => {
    const states = [
      initialEgressState,
      egressReducer(sending(), { type: 'send_failed', status: 422 }),
      egressReducer(sending(), { type: 'send_failed', status: 502 }),
      egressReducer(sending(), { type: 'sent', requestId: 'egress-1' }),
    ]
    for (const state of states) expect(egressReducer(state, { type: 'invalidate' })).toBe(state)
  })

  test('a matching successful direct send becomes terminal, but another request cannot complete it', () => {
    expect(egressReducer(sending(), { type: 'sent', requestId: 'different' }).phase).toBe('sending')
    const sent = egressReducer(sending(), { type: 'sent', requestId: 'egress-1' })
    expect(sent.phase).toBe('sent')
    expect(sent.recovered).toBe(false)
    expect(egressReducer(sent, { type: 'send', storageCleared: true }).phase).toBe('sent')
  })
})

describe('request recovery boundaries', () => {
  test('only matching workspace, purpose, ID and recoverable server states restore', () => {
    expect(validateRecoveredRequest(request, 'case-a', 'egress-1')).toBe(request)
    for (const invalid of [
      { ...request, workspace_id: 'case-b' },
      { ...request, purpose: 'judge' as const },
      { ...request, request_id: 'different' },
      { ...request, status: 'invalidated' as const },
    ]) expect(validateRecoveredRequest(invalid, 'case-a', 'egress-1')).toBeNull()
  })

  test('a restored sent request cannot recover output or resend', () => {
    const restored = egressReducer(initialEgressState, { type: 'restored', request: { ...request, status: 'sent' } })
    expect(restored.phase).toBe('sent')
    expect(restored.recovered).toBe(true)
    expect(egressReducer(restored, { type: 'send', storageCleared: true }).phase).toBe('sent')
  })

  test('network recovery accepts sent only for the same request; approved is not retry permission', () => {
    const sent = egressReducer(sending(), { type: 'send_recovered', request: { ...request, status: 'sent' } })
    expect(sent.phase).toBe('sent')
    expect(sent.recovered).toBe(true)
    for (const result of [null, request, { ...request, status: 'approved' as const }, { ...request, status: 'sent' as const, request_id: 'other' }]) {
      expect(egressReducer(sending(), { type: 'send_recovered', request: result }).phase).toBe('uncertain_failure')
    }
  })

  test('late restore responses cannot replace an active review', () => {
    expect(egressReducer(prepared(), { type: 'restored', request: { ...request, status: 'sent' } }).phase).toBe('prepared')
  })
})

describe('request ID storage safety', () => {
  test('keys separate workspace, template, version and section without separator collisions', () => {
    const keys = [
      requestStorageKey('case-a', 'template', 1, 'section'),
      requestStorageKey('case-b', 'template', 1, 'section'),
      requestStorageKey('case-a', 'other', 1, 'section'),
      requestStorageKey('case-a', 'template', 2, 'section'),
      requestStorageKey('case-a', 'template', 1, 'other'),
      requestStorageKey('a.b', 'c', 1, 'section'),
      requestStorageKey('a', 'b.c', 1, 'section'),
    ]
    expect(new Set(keys).size).toBe(7)
  })

  test('storage writes only the request ID, then verified removal prevents reload recovery', () => {
    const storage = memoryStorage()
    const key = requestStorageKey('case-a', 'template', 1, 'section')
    expect(storeRequestId(storage, key, request.request_id)).toBe(true)
    expect(storage.getItem(key)).toBe('egress-1')
    expect(readStoredRequestId(storage, key)).toEqual({ available: true, id: 'egress-1' })
    expect(clearStoredRequestId(storage, key)).toBe(true)
    expect(readStoredRequestId(storage, key)).toEqual({ available: true, id: null })
  })

  test('unavailable storage cannot authorize a send', () => {
    expect(readStoredRequestId(null, 'key')).toEqual({ available: false, id: null })
    expect(storeRequestId(null, 'key', 'egress-1')).toBe(false)
    expect(clearStoredRequestId(null, 'key')).toBe(false)
    expect(egressReducer(approved(), { type: 'send', storageCleared: clearStoredRequestId(null, 'key') }).phase).toBe('approved')
  })

  test('throwing storage access and removal fail closed', () => {
    const storage: RequestStorage = {
      getItem() { throw new Error('Storage denied') },
      setItem() { throw new Error('Storage denied') },
      removeItem() { throw new Error('Storage denied') },
    }
    expect(readStoredRequestId(storage, 'key').available).toBe(false)
    expect(storeRequestId(storage, 'key', 'egress-1')).toBe(false)
    expect(clearStoredRequestId(storage, 'key')).toBe(false)
  })

  test('silent removal failure is detected rather than permitting an approved reload', () => {
    const storage: RequestStorage = { getItem: () => 'egress-1', setItem() {}, removeItem() {} }
    expect(clearStoredRequestId(storage, 'key')).toBe(false)
    expect(egressReducer(approved(), { type: 'send', storageCleared: clearStoredRequestId(storage, 'key') }).phase).toBe('approved')
  })

  test('silent storage write failures and blank IDs are not reported as saved', () => {
    const storage = memoryStorage()
    expect(storeRequestId(storage, 'key', ' ')).toBe(false)
    expect(storage.getItem('key')).toBeNull()
    const silent: RequestStorage = { getItem: () => null, setItem() {}, removeItem() {} }
    expect(storeRequestId(silent, 'key', 'egress-1')).toBe(false)
  })
})
