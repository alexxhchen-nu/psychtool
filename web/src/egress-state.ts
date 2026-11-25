import type { ApprovalInput, EgressRequest } from './types'

export type EgressPhase = 'restoring' | 'idle' | 'preparing' | 'prepared' | 'approving' | 'approved'
  | 'sending' | 'sent' | 'invalidated' | 'send_interrupted' | 'output_blocked' | 'uncertain_failure' | 'error'

export interface EgressState {
  phase: EgressPhase
  request: EgressRequest | null
  message: string | null
  recovered: boolean
}

export interface ReviewConfirmation {
  reviewer: string
  syntheticReason: string
  confirmed: boolean
}

export type EgressAction =
  | { type: 'restore_start' }
  | { type: 'restored'; request: EgressRequest | null }
  | { type: 'restore_failed' }
  | { type: 'prepare'; acknowledgeUncertain: boolean }
  | { type: 'prepared'; request: EgressRequest }
  | { type: 'prepare_failed'; status: number }
  | { type: 'approve'; confirmation: ReviewConfirmation }
  | { type: 'approved'; request: EgressRequest }
  | { type: 'approval_failed'; status: number }
  | { type: 'send'; storageCleared: boolean }
  | { type: 'sent'; requestId: string }
  | { type: 'send_failed'; status: number }
  | { type: 'send_recovered'; request: EgressRequest | null }
  | { type: 'invalidate' }

export const initialEgressState: EgressState = {
  phase: 'restoring', request: null, message: null, recovered: false,
}

const staleMessage = 'This request is no longer current. Prepare a new request and review its exact input again.'
const uncertainMessage = 'Delivery is uncertain: the model may already have received this request. Do not resend it. Contact an administrator before choosing to prepare a new request.'
const restoredSentMessage = 'This request was already sent. Recovery cannot recover the generated text or resend this request. Check your saved section; a new generation requires a new request.'
export const sendInterruptedMessage = 'Send interrupted — prepare a new request.'

export function approvalInput(request: EgressRequest, confirmation: ReviewConfirmation): ApprovalInput | null {
  if (!confirmation.confirmed || !request.content_hash) return null
  if (request.data_tier === 'real') {
    const reviewer = confirmation.reviewer.trim()
    return reviewer ? { content_hash: request.content_hash, reviewer } : null
  }
  if (request.data_tier === 'synthetic') {
    const reason = confirmation.syntheticReason.trim()
    return reason ? { content_hash: request.content_hash, synthetic_auto_reason: reason } : null
  }
  return null
}

export function isEgressBusy(state: EgressState): boolean {
  return ['restoring', 'preparing', 'approving', 'sending'].includes(state.phase)
}

export function canPrepare(state: EgressState, acknowledgeUncertain: boolean): boolean {
  return !isEgressBusy(state) && (state.phase !== 'uncertain_failure' || acknowledgeUncertain)
}

function sameRequest(left: EgressRequest | null, right: EgressRequest): boolean {
  return left !== null && left.request_id === right.request_id && left.content_hash === right.content_hash
    && left.workspace_id === right.workspace_id && left.purpose === right.purpose
}

function invalidated(state: EgressState): EgressState {
  return { ...state, phase: 'invalidated', message: staleMessage }
}

export function egressReducer(state: EgressState, action: EgressAction): EgressState {
  switch (action.type) {
    case 'restore_start':
      return initialEgressState
    case 'restored':
      if (state.phase !== 'restoring') return state
      if (!action.request) return { phase: 'idle', request: null, message: null, recovered: false }
      if (action.request.status === 'invalidated') return invalidated({ ...state, request: null })
      if (action.request.status === 'send_interrupted') {
        return { phase: 'send_interrupted', request: action.request, message: sendInterruptedMessage, recovered: true }
      }
      return {
        phase: action.request.status, request: action.request, recovered: true,
        message: action.request.status === 'sent' ? restoredSentMessage : 'Request restored. Review the exact input and its sources before continuing.',
      }
    case 'restore_failed':
      return state.phase === 'restoring'
        ? { ...state, phase: 'error', message: 'The saved request could not be checked. Nothing was sent. Check the connection before preparing a new request.' }
        : state
    case 'prepare':
      return canPrepare(state, action.acknowledgeUncertain)
        ? { phase: 'preparing', request: null, message: null, recovered: false }
        : state
    case 'prepared':
      if (state.phase !== 'preparing') return state
      return action.request.status === 'prepared'
        ? { phase: 'prepared', request: action.request, message: null, recovered: false }
        : invalidated(state)
    case 'prepare_failed':
      if (state.phase !== 'preparing') return state
      return {
        ...state, phase: 'error',
        message: action.status === 0
          ? 'The request could not be prepared because the connection failed. Check the connection, then prepare again.'
          : 'The request could not be prepared. Check the selected claims and instructions, then prepare again.',
      }
    case 'approve':
      return state.phase === 'prepared' && state.request && approvalInput(state.request, action.confirmation)
        ? { ...state, phase: 'approving', message: null }
        : state
    case 'approved':
      if (state.phase !== 'approving') return state
      return action.request.status === 'approved' && sameRequest(state.request, action.request)
        ? { ...state, phase: 'approved', request: action.request, message: 'Approved. Nothing has been sent. Use Send once as a separate action.' }
        : invalidated(state)
    case 'approval_failed':
      if (state.phase !== 'approving') return state
      return action.status === 409 ? invalidated(state) : {
        ...state, phase: 'prepared',
        message: 'Approval was not confirmed. Review the request and reviewer or synthetic reason before approving again.',
      }
    case 'send':
      return state.phase === 'approved' && state.request && action.storageCleared
        ? { ...state, phase: 'sending', message: null }
        : state
    case 'sent':
      if (state.phase !== 'sending' || state.request?.request_id !== action.requestId) return state
      return {
        ...state, phase: 'sent', request: { ...state.request, status: 'sent' }, recovered: false,
        message: 'Generated text was placed in the section editor as an unsaved draft. Review it and save the section separately.',
      }
    case 'send_failed':
      if (state.phase !== 'sending') return state
      if (action.status === 403) return {
        ...state, phase: 'approved',
        message: 'The current data-tier and endpoint policy forbids sending. Nothing was sent. Resolve the policy restriction before another explicit send attempt; there is no automatic retry.',
      }
      if (action.status === 409) return invalidated(state)
      return action.status === 422
        ? { ...state, phase: 'output_blocked', message: 'The model was called, but its output was blocked by identifier checks. No output is displayed. This request cannot be sent again.' }
        : { ...state, phase: 'uncertain_failure', message: uncertainMessage }
    case 'send_recovered':
      if (state.phase !== 'sending') return state
      return action.request?.status === 'sent' && sameRequest(state.request, action.request)
        ? { ...state, phase: 'sent', request: action.request, recovered: true, message: restoredSentMessage }
        : { ...state, phase: 'uncertain_failure', message: uncertainMessage }
    case 'invalidate':
      return ['prepared', 'approved', 'preparing', 'approving'].includes(state.phase) ? invalidated(state) : state
  }
}

export function validateRecoveredRequest(request: EgressRequest | null, workspaceId: string, requestId: string): EgressRequest | null {
  if (!request || request.workspace_id !== workspaceId || request.purpose !== 'section_generation'
    || request.request_id !== requestId
    || !['prepared', 'approved', 'sent', 'send_interrupted'].includes(request.status)) return null
  return request
}

export interface RequestStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
  removeItem(key: string): void
}

export function requestStorageKey(workspaceId: string, templateId: string, templateVersion: number, sectionId: string): string {
  return `psychtool.egress.${JSON.stringify([workspaceId, templateId, templateVersion, sectionId])}`
}

export function sessionRequestStorage(): RequestStorage | null {
  try { return window.sessionStorage } catch { return null }
}

export function readStoredRequestId(storage: RequestStorage | null, key: string): { available: boolean; id: string | null } {
  if (!storage) return { available: false, id: null }
  try { return { available: true, id: storage.getItem(key) || null } } catch { return { available: false, id: null } }
}

export function storeRequestId(storage: RequestStorage | null, key: string, requestId: string): boolean {
  if (!storage || !requestId.trim()) return false
  try {
    storage.setItem(key, requestId)
    return storage.getItem(key) === requestId
  } catch { return false }
}

/** A successful remove call alone is insufficient: verify the resumable ID is gone. */
export function clearStoredRequestId(storage: RequestStorage | null, key: string): boolean {
  if (!storage) return false
  try {
    storage.removeItem(key)
    return storage.getItem(key) === null
  } catch { return false }
}
