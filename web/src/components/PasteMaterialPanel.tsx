import { useEffect, useId, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, pasteMaterial } from '../api'
import type { UploadResult } from '../types'
import { validatePaste } from '../case-form'
import type { PasteFieldErrors } from '../case-form'
import { heldBackNotice, summarizeUpload, uploadErrorMessage } from '../upload'
import type { UploadSummary } from '../upload'

interface PasteMaterialPanelProps {
  workspaceId: string
  onPasted: (result: UploadResult) => void | Promise<void>
  onReview: (materialId: string) => void
  onBusyChange: (busy: boolean) => void
}

export default function PasteMaterialPanel({ workspaceId, onPasted, onReview, onBusyChange }: PasteMaterialPanelProps) {
  const id = useId()
  const [materialId, setMaterialId] = useState('')
  const [title, setTitle] = useState('')
  const [provider, setProvider] = useState('')
  const [date, setDate] = useState('')
  const [text, setText] = useState('')
  const [syntheticConfirmed, setSyntheticConfirmed] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<PasteFieldErrors>({})
  const [error, setError] = useState('')
  const [result, setResult] = useState<UploadSummary | null>(null)
  const [heldBack, setHeldBack] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const lifecycle = useRef<symbol | null>(null)

  useEffect(() => {
    lifecycle.current = Symbol()
    return () => { lifecycle.current = null }
  }, [])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const currentLifecycle = lifecycle.current
    if (busyRef.current || currentLifecycle === null) return

    const errors = validatePaste({ materialId, title, provider, date, text, syntheticConfirmed })
    setFieldErrors(errors)
    setError('')
    const firstInvalid = Object.keys(errors)[0]
    if (firstInvalid) {
      event.currentTarget.querySelector<HTMLElement>(`[name="${firstInvalid}"]`)?.focus()
      return
    }

    busyRef.current = true
    setBusy(true)
    setResult(null)
    setHeldBack(null)
    const isCurrent = () => lifecycle.current === currentLifecycle
    try {
      onBusyChange(true)
      const uploaded = await pasteMaterial(workspaceId, {
        material_id: materialId,
        title: title.trim(),
        provider: provider.trim(),
        date: date.trim(),
        text,
        synthetic_confirmed: true,
      })
      if (!isCurrent()) return
      setResult(summarizeUpload(uploaded))
      // R13 (ADR 0013): same held-back notice as the file upload; no
      // release/override action exists in M1.
      setHeldBack(heldBackNotice(uploaded.blocked_paragraphs))
      try {
        await onPasted(uploaded)
      } catch {
        if (isCurrent()) {
          setError('The material was saved, but the material list could not refresh. Reopen the workspace before pasting it again.')
        }
      }
    } catch (cause) {
      // Surface the server's fixed {detail, reason} message when present
      // (type/size rejections and the R13 protected-content reasons),
      // exactly like the file upload panel.
      if (isCurrent()) {
        setError(cause instanceof ApiError && cause.serverMessage
          ? uploadErrorMessage(cause)
          : 'The pasted text could not be saved. Check the fields and try again.')
      }
    } finally {
      if (isCurrent()) {
        busyRef.current = false
        setBusy(false)
        onBusyChange(false)
      }
    }
  }

  return (
    <section className="names-panel paste-panel" aria-labelledby={`${id}-heading`}>
      <div className="names-panel-copy">
        <h3 id={`${id}-heading`}>Paste synthetic text.</h3>
        <p>The text is checked for identifiers and stored as a new material version, exactly like a file upload. Pasting does not send anything to a model.</p>
        <p>Only paste text you know is synthetic. Automatic detection can miss identifying information; review the material and claims before any model request.</p>
      </div>
      <form className="upload-fields" onSubmit={handleSubmit} noValidate aria-busy={busy}>
        <label className="field-label" htmlFor={`${id}-materialId`}>
          Anonymous material ID (required)
          <input
            id={`${id}-materialId`}
            name="materialId"
            className="text-input"
            value={materialId}
            onChange={(event) => setMaterialId(event.target.value)}
            maxLength={64}
            autoCapitalize="off"
            autoComplete="off"
            spellCheck={false}
            required
            disabled={busy}
            aria-invalid={Boolean(fieldErrors.materialId)}
            aria-describedby={`${id}-materialId-help${fieldErrors.materialId ? ` ${id}-materialId-error` : ''}`}
          />
          <span id={`${id}-materialId-help`}>Use 1–64 ASCII letters, digits, underscores or hyphens. Do not use a person's name. Reusing an ID creates a new material version.</span>
          {fieldErrors.materialId && <span id={`${id}-materialId-error`} role="alert">{fieldErrors.materialId}</span>}
        </label>
        <label className="field-label" htmlFor={`${id}-title`}>
          Title (required)
          <input
            id={`${id}-title`}
            name="title"
            className="text-input"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            required
            disabled={busy}
            aria-invalid={Boolean(fieldErrors.title)}
            aria-describedby={fieldErrors.title ? `${id}-title-error` : undefined}
          />
          {fieldErrors.title && <span id={`${id}-title-error`} role="alert">{fieldErrors.title}</span>}
        </label>
        <label className="field-label" htmlFor={`${id}-provider`}>
          Provider (required)
          <input
            id={`${id}-provider`}
            name="provider"
            className="text-input"
            value={provider}
            onChange={(event) => setProvider(event.target.value)}
            required
            disabled={busy}
            aria-invalid={Boolean(fieldErrors.provider)}
            aria-describedby={fieldErrors.provider ? `${id}-provider-error` : undefined}
          />
          {fieldErrors.provider && <span id={`${id}-provider-error`} role="alert">{fieldErrors.provider}</span>}
        </label>
        <label className="field-label" htmlFor={`${id}-date`}>
          Date (required)
          <input
            id={`${id}-date`}
            name="date"
            className="text-input"
            type="date"
            value={date}
            onChange={(event) => setDate(event.target.value)}
            required
            disabled={busy}
            aria-invalid={Boolean(fieldErrors.date)}
            aria-describedby={fieldErrors.date ? `${id}-date-error` : undefined}
          />
          {fieldErrors.date && <span id={`${id}-date-error`} role="alert">{fieldErrors.date}</span>}
        </label>
        <label className="field-label" htmlFor={`${id}-text`}>
          Synthetic text (required)
          <textarea
            id={`${id}-text`}
            name="text"
            className="editor-input"
            rows={6}
            value={text}
            onChange={(event) => setText(event.target.value)}
            required
            disabled={busy}
            aria-invalid={Boolean(fieldErrors.text)}
            aria-describedby={fieldErrors.text ? `${id}-text-error` : undefined}
          />
          {fieldErrors.text && <span id={`${id}-text-error`} role="alert">{fieldErrors.text}</span>}
        </label>
        <label className="confirmation-label">
          <input
            type="checkbox"
            name="syntheticConfirmed"
            checked={syntheticConfirmed}
            disabled={busy}
            aria-invalid={Boolean(fieldErrors.syntheticConfirmed)}
            onChange={(event) => setSyntheticConfirmed(event.target.checked)}
          />
          <span>I confirm this text is entirely synthetic and contains no real patient information.</span>
        </label>
        {fieldErrors.syntheticConfirmed && <p role="alert">{fieldErrors.syntheticConfirmed}</p>}
        <button className="primary-button" type="submit" disabled={busy || !workspaceId}>
          {busy ? 'Saving…' : 'Save pasted material'}
        </button>
      </form>
      {error && <p className="error-banner" role="alert">{error}</p>}
      {heldBack && (
        <p className="held-back-notice" role="status" data-testid="held-back-notice">{heldBack}</p>
      )}
      {result && (
        <div className="upload-result">
          <div role="status" aria-live="polite">
            <h4>Material saved</h4>
            <dl>
              <dt>Material ID</dt><dd>{result.materialId}</dd>
              <dt>Version</dt><dd>{result.version}</dd>
              <dt>Passages</dt><dd>{result.passageCount}</dd>
              <dt>Identifier categories detected</dt>
              <dd>{result.identifierCategories.length ? result.identifierCategories.join(', ') : 'None detected. This does not mean the material is de-identified.'}</dd>
            </dl>
            <p>Manual review is required. Automatic checks may miss identifying information; review the source material and intake claims before any model request.</p>
          </div>
          <button
            className="primary-button"
            type="button"
            disabled={busy}
            onClick={() => {
              if (!busyRef.current && lifecycle.current !== null) onReview(result.materialId)
            }}
          >Review intake claims</button>
        </div>
      )}
    </section>
  )
}
