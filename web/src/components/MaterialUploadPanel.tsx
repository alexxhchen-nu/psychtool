import { useEffect, useId, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { uploadMaterial } from '../api'
import type { UploadResult } from '../types'
import { summarizeUpload, UPLOAD_ACCEPT, uploadErrorMessage, validateMaterialUpload } from '../upload'
import type { UploadFieldErrors, UploadSummary } from '../upload'

interface MaterialUploadPanelProps {
  workspaceId: string
  onUploaded: (result: UploadResult) => void | Promise<void>
  onReview: (materialId: string) => void
  onBusyChange: (busy: boolean) => void
}

export default function MaterialUploadPanel({ workspaceId, onUploaded, onReview, onBusyChange }: MaterialUploadPanelProps) {
  const id = useId()
  const [file, setFile] = useState<File | null>(null)
  const [materialId, setMaterialId] = useState('')
  const [title, setTitle] = useState('')
  const [provider, setProvider] = useState('')
  const [date, setDate] = useState('')
  const [fieldErrors, setFieldErrors] = useState<UploadFieldErrors>({})
  const [error, setError] = useState('')
  const [result, setResult] = useState<UploadSummary | null>(null)
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const lifecycle = useRef<symbol | null>(null)

  useEffect(() => {
    // Each effect setup has its own identity, including StrictMode's second setup.
    lifecycle.current = Symbol()
    return () => { lifecycle.current = null }
  }, [])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const currentLifecycle = lifecycle.current
    if (busyRef.current || currentLifecycle === null) return

    const errors = validateMaterialUpload({ file, materialId, title, provider, date })
    setFieldErrors(errors)
    setError('')
    const firstInvalid = Object.keys(errors)[0]
    if (firstInvalid) {
      event.currentTarget.querySelector<HTMLInputElement>(`[name="${firstInvalid}"]`)?.focus()
      return
    }
    if (!file) return

    // React state alone cannot block a second submit in the same event turn.
    busyRef.current = true
    setBusy(true)
    setResult(null)
    const isCurrent = () => lifecycle.current === currentLifecycle
    try {
      onBusyChange(true)
      const form = new FormData()
      form.append('file', file)
      form.append('material_id', materialId)
      form.append('title', title.trim())
      form.append('provider', provider.trim())
      form.append('date', date.trim())
      const uploaded = await uploadMaterial(workspaceId, form)
      if (!isCurrent()) return
      setResult(summarizeUpload(uploaded))
      try {
        await onUploaded(uploaded)
      } catch {
        if (isCurrent()) {
          setError('The material was uploaded, but the material list could not refresh. Reopen the workspace before uploading it again.')
        }
      }
    } catch (cause) {
      if (isCurrent()) setError(uploadErrorMessage(cause))
    } finally {
      if (isCurrent()) {
        busyRef.current = false
        setBusy(false)
        onBusyChange(false)
      }
    }
  }

  return (
    <section className="names-panel upload-panel" aria-labelledby={`${id}-heading`}>
      <div className="names-panel-copy">
        <h3 id={`${id}-heading`}>Upload source material.</h3>
        <p>The file reaches the psychtool Web server for parsing and identifier checks. Uploading does not send it to a model.</p>
        <p>Automatic detection can miss identifying information. Manually review the material and claims before preparing any model request. Use only synthetic or public development materials.</p>
      </div>
      <form className="upload-fields" onSubmit={handleSubmit} noValidate aria-busy={busy}>
        <label className="field-label" htmlFor={`${id}-file`}>
          File (required)
          <input
            id={`${id}-file`}
            name="file"
            className="text-input"
            type="file"
            accept={UPLOAD_ACCEPT}
            required
            disabled={busy}
            aria-invalid={Boolean(fieldErrors.file)}
            aria-describedby={`${id}-file-help${fieldErrors.file ? ` ${id}-file-error` : ''}`}
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
          <span id={`${id}-file-help`}>TXT, Markdown, PDF, PNG or JPEG. Maximum 10 MiB (10,485,760 bytes). PDF and images require server-side OCR.</span>
          {fieldErrors.file && <span id={`${id}-file-error`} role="alert">{fieldErrors.file}</span>}
        </label>
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
        <button className="primary-button" type="submit" disabled={busy || !workspaceId}>
          {busy ? 'Uploading…' : 'Upload material'}
        </button>
      </form>
      {error && <p className="error-banner" role="alert">{error}</p>}
      {result && (
        <div className="upload-result">
          <div role="status" aria-live="polite">
            <h4>Material uploaded</h4>
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
