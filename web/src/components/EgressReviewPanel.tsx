import { useEffect, useId, useRef, useState } from 'react'
import { ApiError, approveEgress, getEgress, prepareEgress, sendEgress } from '../api'
import { egressPrimaryStepActive } from '../section-editor'
import {
  approvalInput,
  canPrepare,
  clearStoredRequestId,
  egressReducer,
  initialEgressState,
  isEgressBusy,
  readStoredRequestId,
  requestStorageKey,
  sessionRequestStorage,
  storeRequestId,
  validateRecoveredRequest,
} from '../egress-state'
import type { EgressAction, EgressPhase, EgressState } from '../egress-state'
import type { EgressRequest } from '../types'

interface Props {
  workspaceId: string
  templateId: string
  templateVersion: number
  sectionId: string
  sectionTitle: string
  claimIds: string[]
  sourceRevision: number
  onGenerated: (text: string, claimIds: string[]) => void
  onBusyChange: (busy: boolean) => void
  onPrimaryStepChange?: (active: boolean) => void
  disabled: boolean
}

const phaseLabels: Record<EgressPhase, string> = {
  restoring: 'Checking saved request...', idle: 'No request prepared', preparing: 'Preparing request...',
  prepared: 'Prepared — review required', approving: 'Approving request...', approved: 'Approved — not sent',
  sending: 'Sending once...', sent: 'Sent — no resend', invalidated: 'Invalidated — prepare again',
  send_interrupted: 'Send interrupted — prepare a new request',
  output_blocked: 'Output blocked — no resend', uncertain_failure: 'Delivery uncertain — no resend', error: 'Request unavailable',
}
const storageMessage = 'The browser could not safely update or read the saved request ID. Recovery may be unavailable. Sending is blocked unless removal of the saved ID can be verified.'

function errorStatus(error: unknown): number {
  return error instanceof ApiError ? error.status : -1
}

export default function EgressReviewPanel({
  workspaceId, templateId, templateVersion, sectionId, sectionTitle, claimIds, sourceRevision,
  onGenerated, onBusyChange, onPrimaryStepChange, disabled,
}: Props) {
  const id = useId()
  const [state, setState] = useState<EgressState>(initialEgressState)
  const [instructions, setInstructions] = useState('')
  const [reviewer, setReviewer] = useState('')
  const [syntheticReason, setSyntheticReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [acknowledgeUncertain, setAcknowledgeUncertain] = useState(false)
  const [storageWarning, setStorageWarning] = useState('')
  const stateRef = useRef(state)
  const alive = useRef(false)
  const generation = useRef(0)
  const busyRef = useRef(true)
  const callbacks = useRef({ onGenerated, onBusyChange })
  callbacks.current = { onGenerated, onBusyChange }
  const disabledRef = useRef(disabled)
  disabledRef.current = disabled

  const storageKey = requestStorageKey(workspaceId, templateId, templateVersion, sectionId)
  const contextRef = useRef(storageKey)
  contextRef.current = storageKey
  // A restored request establishes its baseline only after GET; current selections do not rewrite its preview.
  const inputsKey = JSON.stringify([[...claimIds].sort(), sourceRevision, instructions])
  const inputsRef = useRef(inputsKey)
  inputsRef.current = inputsKey
  const requestInputsRef = useRef<string | null>(null)

  function transition(action: EgressAction): EgressState {
    const next = egressReducer(stateRef.current, action)
    stateRef.current = next
    setState(next)
    return next
  }

  function current(token: number, phase?: EgressPhase): boolean {
    return alive.current && generation.current === token && contextRef.current === storageKey
      && (phase === undefined || stateRef.current.phase === phase)
  }

  function begin(): number | null {
    if (!alive.current || busyRef.current || disabledRef.current) return null
    busyRef.current = true
    const token = ++generation.current
    callbacks.current.onBusyChange(true)
    return token
  }

  function finish(token: number) {
    if (!current(token)) return
    busyRef.current = false
    callbacks.current.onBusyChange(false)
  }

  function clearSavedId(): boolean {
    const removed = clearStoredRequestId(sessionRequestStorage(), storageKey)
    setStorageWarning(removed ? '' : storageMessage)
    return removed
  }

  function saveId(requestId: string) {
    const saved = storeRequestId(sessionRequestStorage(), storageKey, requestId)
    setStorageWarning(saved ? '' : storageMessage)
  }

  function invalidateReadiness() {
    const previous = stateRef.current
    const next = transition({ type: 'invalidate' })
    if (next !== previous) {
      setConfirmed(false)
      clearSavedId()
    }
  }

  function inputsStillCurrent(): boolean {
    if (requestInputsRef.current === inputsRef.current) return true
    invalidateReadiness()
    return false
  }

  useEffect(() => {
    alive.current = true
    const token = ++generation.current
    busyRef.current = true
    requestInputsRef.current = null
    transition({ type: 'restore_start' })
    callbacks.current.onBusyChange(true)

    async function restore() {
      try {
        const stored = readStoredRequestId(sessionRequestStorage(), storageKey)
        if (!stored.available) setStorageWarning(storageMessage)
        if (!stored.id) {
          transition({ type: 'restored', request: null })
          return
        }
        const response = await getEgress(workspaceId, stored.id)
        if (!current(token)) return
        const request = validateRecoveredRequest(response, workspaceId, stored.id)
        if (!request) clearSavedId()
        requestInputsRef.current = inputsRef.current
        transition({ type: 'restored', request })
      } catch (error) {
        if (!current(token)) return
        if ([404, 409].includes(errorStatus(error))) {
          clearSavedId()
          transition({ type: 'restored', request: null })
        } else {
          transition({ type: 'restore_failed' })
        }
      } finally {
        finish(token)
      }
    }
    void restore()
    return () => {
      alive.current = false
      ++generation.current
      busyRef.current = false
      callbacks.current.onBusyChange(false)
    }
    // Context identity owns this lifecycle; callback refs keep parent handlers fresh without restarting GET.
  }, [storageKey, workspaceId])

  useEffect(() => {
    if (stateRef.current.phase !== 'restoring' && requestInputsRef.current !== null
      && requestInputsRef.current !== inputsKey) invalidateReadiness()
  }, [inputsKey])

  async function prepare() {
    if (!canPrepare(stateRef.current, acknowledgeUncertain)) return
    const token = begin()
    if (token === null) return
    const baseline = inputsRef.current
    requestInputsRef.current = baseline
    transition({ type: 'prepare', acknowledgeUncertain })
    clearSavedId()
    setConfirmed(false)
    setReviewer('')
    setSyntheticReason('')
    setAcknowledgeUncertain(false)
    try {
      const response = await prepareEgress(workspaceId, {
        template_id: templateId, template_version: templateVersion, section_id: sectionId,
        claim_ids: [...claimIds],
        instructions: `Write the "${sectionTitle}" section (${sectionId}). Preserve attribution, conflicting accounts, and uncertainty; never invent missing facts, scores, or diagnoses.\n${instructions}`,
      })
      if (!current(token)) return
      if (inputsRef.current !== baseline || !current(token, 'preparing')) {
        invalidateReadiness()
        return
      }
      const request = validateRecoveredRequest(response, workspaceId, response.request_id)
      if (!request || request.status !== 'prepared') {
        transition({ type: 'prepare_failed', status: -1 })
        return
      }
      transition({ type: 'prepared', request })
      saveId(request.request_id)
    } catch (error) {
      if (current(token)) transition({ type: 'prepare_failed', status: errorStatus(error) })
    } finally {
      finish(token)
    }
  }

  async function approve() {
    const request = stateRef.current.request
    if (stateRef.current.phase !== 'prepared' || !request || !inputsStillCurrent()) return
    const confirmation = { reviewer, syntheticReason, confirmed }
    const input = approvalInput(request, confirmation)
    if (!input) return
    const token = begin()
    if (token === null) return
    const baseline = inputsRef.current
    transition({ type: 'approve', confirmation })
    try {
      const response = await approveEgress(workspaceId, request.request_id, input)
      if (!current(token)) return
      if (inputsRef.current !== baseline || !current(token, 'approving')) {
        invalidateReadiness()
        return
      }
      const next = transition({ type: 'approved', request: response })
      if (next.phase === 'invalidated') clearSavedId()
      else saveId(request.request_id)
    } catch (error) {
      if (!current(token)) return
      const next = transition({ type: 'approval_failed', status: errorStatus(error) })
      if (next.phase === 'invalidated') clearSavedId()
    } finally {
      finish(token)
    }
  }

  async function recoverAfterSend(token: number, request: EgressRequest) {
    let recovered: EgressRequest | null = null
    try {
      const response = await getEgress(workspaceId, request.request_id)
      if (!current(token)) return
      recovered = validateRecoveredRequest(response, workspaceId, request.request_id)
    } catch {
      if (!current(token)) return
    }
    const next = transition({ type: 'send_recovered', request: recovered })
    // Only a terminal sent ID may be restored after unknown delivery. GET never supplies output text.
    if (next.phase === 'sent') saveId(request.request_id)
  }

  async function send() {
    const request = stateRef.current.request
    if (stateRef.current.phase !== 'approved' || !request || !inputsStillCurrent()) return
    const token = begin()
    if (token === null) return
    try {
      // Fail closed BEFORE POST. Reload must never restore an approved unknown-delivery request.
      const storageCleared = clearSavedId()
      if (!storageCleared) return
      const next = transition({ type: 'send', storageCleared })
      if (next.phase !== 'sending') return
      let result
      try {
        result = await sendEgress(workspaceId, request.request_id)
      } catch (error) {
        if (!current(token)) return
        const status = errorStatus(error)
        if (status === 0) await recoverAfterSend(token, request)
        else {
          const failed = transition({ type: 'send_failed', status })
          // A policy denial explicitly means no delivery; it is not an uncertain-send retry.
          if (failed.phase === 'approved') saveId(request.request_id)
        }
        return
      }
      if (!current(token)) return
      if (!result || result.request_id !== request.request_id || result.status !== 'sent' || typeof result.text !== 'string') {
        await recoverAfterSend(token, request)
        return
      }
      transition({ type: 'sent', requestId: result.request_id })
      saveId(result.request_id)
      callbacks.current.onGenerated(result.text, request.source_refs.filter((source) => source.kind === 'claim').map((source) => source.id))
    } finally {
      finish(token)
    }
  }

  const request = state.request
  const busy = isEgressBusy(state)
  const locked = disabled || busy
  const confirmation = { reviewer, syntheticReason, confirmed }
  const approvalReady = request !== null && approvalInput(request, confirmation) !== null
  const terminal = ['sent', 'output_blocked', 'uncertain_failure', 'send_interrupted'].includes(state.phase)
  const errorMessage = ['error', 'invalidated', 'output_blocked', 'uncertain_failure', 'send_interrupted'].includes(state.phase)
  const primaryStepActive = egressPrimaryStepActive(state.phase, approvalReady, locked)

  useEffect(() => {
    onPrimaryStepChange?.(primaryStepActive)
  }, [onPrimaryStepChange, primaryStepActive])
  useEffect(() => {
    return () => { onPrimaryStepChange?.(false) }
    // Notify the parent once when this panel unmounts (section change or clinician-authored).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <section className="egress-panel" aria-labelledby={`${id}-title`} aria-busy={busy} data-testid="egress-panel" data-primary-step={primaryStepActive ? 'true' : 'false'}>
      <h3 id={`${id}-title`}>Model request for {sectionTitle}</h3>
      <p aria-live="polite"><strong>{phaseLabels[state.phase]}</strong></p>
      <p>Prepare freezes the exact model input. Review it, approve it, then send once. Generated text is not saved automatically.</p>
      {state.message && <p role={errorMessage ? 'alert' : 'status'}>{state.message}</p>}
      {storageWarning && <p role="alert">{storageWarning}</p>}

      <label className="field-label" htmlFor={`${id}-instructions`}>Generation instructions (optional)</label>
      <textarea className="text-input" id={`${id}-instructions`} rows={3} value={instructions} disabled={locked}
        onChange={(event) => setInstructions(event.target.value)} />
      <p>{claimIds.length} selected {claimIds.length === 1 ? 'claim' : 'claims'} for a new request.</p>
      {state.phase === 'uncertain_failure' && (
        <label className="confirmation-label">
          <input type="checkbox" checked={acknowledgeUncertain} disabled={locked}
            onChange={(event) => setAcknowledgeUncertain(event.target.checked)} />
          <span>I understand the earlier request may have reached the model and intentionally want a new request.</span>
        </label>
      )}
      <button type="button" className="secondary-button" disabled={locked || !canPrepare(state, acknowledgeUncertain)}
        aria-busy={state.phase === 'preparing'} onClick={() => void prepare()}>
        {state.phase === 'preparing' ? 'Preparing...' : request || terminal || state.phase === 'invalidated' ? 'Prepare new request' : 'Prepare request'}
      </button>

      {request && <>
        <dl className="egress-meta">
          <dt>Request ID</dt><dd><code>{request.request_id}</code></dd>
          <dt>Data tier</dt><dd>{request.data_tier}</dd>
          <dt>Provider endpoint</dt><dd>{request.provider_base_url}</dd>
          <dt>Model</dt><dd>{request.model}</dd>
          <dt>SHA-256 content hash</dt><dd><code>{request.content_hash}</code></dd>
          {request.approval_mode && <><dt>Approval mode</dt><dd>{request.approval_mode === 'human' ? 'Human review' : 'Explicit synthetic approval'}</dd></>}
          {request.reviewer && <><dt>Reviewer label (unverified)</dt><dd>{request.reviewer}</dd></>}
          {request.approval_reason && <><dt>Synthetic approval reason</dt><dd>{request.approval_reason}</dd></>}
        </dl>
        <h4>Frozen source references</h4>
        {request.source_refs.length > 0
          ? <ul className="egress-sources">{request.source_refs.map((source) => (
            <li key={`${source.kind}:${source.id}:${source.version}`}>{source.kind}: {source.id} · version {source.version}</li>
          ))}</ul>
          : <p>No source references.</p>}
        <h4>Identifier categories replaced</h4>
        <p>{request.identifier_categories.length > 0 ? request.identifier_categories.join(' · ') : 'No identifier categories detected.'}</p>
        <p>Automatic detection can miss identifiers. Review the entire input; this is not a compliance assurance.</p>
        <h4 id={`${id}-preview-title`}>Exact model input</h4>
        <pre className="egress-preview" tabIndex={0} role="region" aria-labelledby={`${id}-preview-title`}>{request.preview}</pre>

        {(state.phase === 'prepared' || state.phase === 'approving') && <>
          {request.data_tier === 'real' ? <>
            <label className="field-label" htmlFor={`${id}-reviewer`}>Reviewer label</label>
            <input className="text-input" id={`${id}-reviewer`} type="text" value={reviewer} disabled={locked}
              aria-describedby={`${id}-reviewer-note`} onChange={(event) => setReviewer(event.target.value)} />
            <p id={`${id}-reviewer-note`}>A self-declared label, not a verified identity or electronic signature.</p>
          </> : <>
            <label className="field-label" htmlFor={`${id}-reason`}>Synthetic approval reason</label>
            <textarea className="text-input" id={`${id}-reason`} rows={2} value={syntheticReason} disabled={locked}
              onChange={(event) => setSyntheticReason(event.target.value)} />
          </>}
          <label className="confirmation-label">
            <input type="checkbox" checked={confirmed} disabled={locked}
              onChange={(event) => setConfirmed(event.target.checked)} />
            <span>{request.data_tier === 'real'
              ? 'I reviewed the complete exact input, sources and destination, and approve this request.'
              : 'I confirm this request uses synthetic data, reviewed the complete input and destination, and explicitly approve it for the reason above.'}</span>
          </label>
          <button type="button" className="primary-button" disabled={locked || !approvalReady}
            aria-busy={state.phase === 'approving'} onClick={() => void approve()}>
            {state.phase === 'approving' ? 'Approving...' : 'Approve request'}
          </button>
          <p>Approval alone does not send anything.</p>
        </>}
        {(state.phase === 'approved' || state.phase === 'sending') && (
          <button type="button" className="primary-button" disabled={locked}
            aria-busy={state.phase === 'sending'} onClick={() => void send()}>
            {state.phase === 'sending' ? 'Sending once...' : 'Send once'}
          </button>
        )}
      </>}
    </section>
  )
}
