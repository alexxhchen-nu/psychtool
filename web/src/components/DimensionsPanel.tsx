import { useEffect, useRef, useState } from 'react'
import { getDimensions, setEvidenceDimension, uploadMaterialWithKind } from '../api'
import {
  buildGroups,
  canConfirm,
  canReject,
  dimensionChipLabel,
  dimensionSourceLabel,
  NO_DIMENSION_LABEL,
  NOT_MAPPED_GROUP,
  reviewSummaryLine,
} from '../dimensions'
import { highlightParts, reasonLine, roleLabel } from '../evidence'
import { correctionToast } from '../correction'
import type { DimensionsResponse, EvidenceInvalidation, EvidenceItem, Material } from '../types'

const SUB_WITH_LIST =
  'Every dimension name comes from your upload “{title}”. The system does not use any built-in official list or criteria text.'
const SUB_WITHOUT_LIST =
  'No dimension list has been uploaded for this case, so no evidence gets a dimension.'
const NOTICE_LEAD =
  'Dimension mapping only helps organize evidence. This is not a diagnosis. The diagnosis is yours.'
const NOTICE_TAIL =
  ' Mappings the system is unsure about are marked “Needs review” until you confirm or change them.'
const EMPTY_STATE_TEXT =
  'Upload your own dimension list or an approved excerpt to see dimension mapping.'
const EMPTY_GROUP_TEXT = 'No evidence mapped to this dimension.'

interface DimensionsPanelProps {
  workspaceId: string
  materials: Material[]
  busy: boolean
  syntheticConfirmed: boolean
  /** R6 (PT-09 / ADR 0018): the case-level toast + pill/revision updater. */
  onCorrection?: (toast: string, invalidation: EvidenceInvalidation) => void
}

export default function DimensionsPanel({ workspaceId, materials, busy, syntheticConfirmed, onCorrection }: DimensionsPanelProps) {
  const [view, setView] = useState<DimensionsResponse | null>(null)
  const [selected, setSelected] = useState<EvidenceItem | null>(null)
  const [listHighlight, setListHighlight] = useState<{ dimensionId: string } | null>(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const lifecycle = useRef<symbol | null>(null)

  useEffect(() => {
    lifecycle.current = Symbol()
    return () => { lifecycle.current = null }
  }, [])

  useEffect(() => {
    const current = lifecycle.current
    if (current === null) return
    let active = true
    ;(async () => {
      try {
        const response = await getDimensions(workspaceId)
        if (!active || lifecycle.current !== current) return
        setView(response)
        setError('')
      } catch {
        if (!active || lifecycle.current !== current) return
        setView(null)
        setError('Could not load dimension mapping. Reload to try again.')
      }
    })()
    return () => { active = false }
  }, [workspaceId, materials])

  async function choose(item: EvidenceItem, choice: Parameters<typeof setEvidenceDimension>[2]) {
    const current = lifecycle.current
    if (current === null || saving) return
    setSaving(true)
    try {
      const result = await setEvidenceDimension(workspaceId, item.id, choice)
      if (lifecycle.current !== current) return
      // R6 (PT-09): surface the server's exact toast and let the case level
      // update section pills / egress revision (never unsaved editor text).
      const toast = correctionToast(result)
      if (toast && result.invalidation) onCorrection?.(toast, result.invalidation)
      const response = await getDimensions(workspaceId)
      if (lifecycle.current !== current) return
      setView(response)
      const updated = response.items.find((row) => row.id === item.id)
      if (updated) setSelected(updated)
      setError('')
    } catch {
      if (lifecycle.current !== current) return
      setError('Could not save your choice. Reload to try again.')
    } finally {
      if (lifecycle.current === current) setSaving(false)
    }
  }

  const markRef = useRef<HTMLElement | null>(null)
  useEffect(() => {
    markRef.current?.scrollIntoView({ block: 'center' })
  }, [selected, listHighlight])

  // -- evidence source area (same approach as EvidencePanel) ----------------
  const material = selected
    ? materials.find((item) => item.id === selected.material_id)
    : undefined
  const stale = Boolean(
    selected && material && material.version !== selected.material_version,
  )
  const passageText =
    selected && material && !stale
      ? material.passages.find((passage) => passage.id === selected.passage_id)?.text
      : undefined
  const parts = selected && passageText !== undefined
    ? highlightParts(passageText, selected.start, selected.end)
    : null

  // -- list source area ------------------------------------------------------
  const listMaterial = view?.list
    ? materials.find((item) => item.id === view.list!.material_id)
    : undefined
  const highlightedDimension = listHighlight
    ? view?.dimensions.find((d) => d.id === listHighlight.dimensionId)
    : undefined

  if (view && !view.has_list) {
    return (
      <section className="names-panel dimensions-panel" aria-label="Dimension mapping">
        <div className="names-panel-copy">
          <h3>Dimension mapping</h3>
          <p>{SUB_WITHOUT_LIST}</p>
          <p data-testid="not-diagnosis">
            <strong>{NOTICE_LEAD}</strong>
            {NOTICE_TAIL}
          </p>
        </div>
        {error && <p className="error-banner" role="alert">{error}</p>}
        <p role="status">{EMPTY_STATE_TEXT}</p>
        {!syntheticConfirmed && (
          <p className="muted">Confirm this case uses only synthetic or separately approved materials before uploading (use “Upload material” once).</p>
        )}
        <UploadListButton workspaceId={workspaceId} disabled={busy || !syntheticConfirmed} onUploaded={() => {
          void getDimensions(workspaceId).then(setView)
        }} />
      </section>
    )
  }

  const { groups, rest } = view
    ? buildGroups(view.dimensions, view.items)
    : { groups: [], rest: [] }

  return (
    <section className="names-panel dimensions-panel" aria-label="Dimension mapping">
      <div className="names-panel-copy">
        <h3>Dimension mapping</h3>
        {view?.list && <p>{SUB_WITH_LIST.replace('{title}', view.list.title)}</p>}
        <p data-testid="not-diagnosis">
          <strong>{NOTICE_LEAD}</strong>
          {NOTICE_TAIL}
        </p>
      </div>
      {error && <p className="error-banner" role="alert">{error}</p>}
      {!view && !error && <p role="status">Loading dimension mapping…</p>}
      {view && (
        <>
          <p role="status" data-testid="dimension-summary">
            {reviewSummaryLine(view.needs_review_count, view.items.length)}
          </p>
          {groups.map((group) => (
            <div className="dimension-group" key={group.dimension.id} data-testid="dimension-group">
              <div className="dimension-group-header">
                <strong>{group.dimension.name}</strong>
                <span>{group.items.length}</span>
                <button
                  type="button"
                  className="ghost-button"
                  onClick={() => setListHighlight({ dimensionId: group.dimension.id })}
                >
                  {dimensionSourceLabel(group.dimension.paragraph)}
                </button>
              </div>
              {group.items.length === 0 && (
                <p className="muted">{EMPTY_GROUP_TEXT}</p>
              )}
              {group.items.map((item) => (
                <DimensionRow
                  key={item.id}
                  item={item}
                  dimensions={view.dimensions}
                  busy={busy || saving}
                  onSelect={() => setSelected(item)}
                  onChoose={(choice) => choose(item, choice)}
                />
              ))}
            </div>
          ))}
          <div className="dimension-group" data-testid="dimension-group-rest">
            <div className="dimension-group-header">
              <strong>{NOT_MAPPED_GROUP}</strong>
              <span>{rest.length}</span>
            </div>
            {rest.map((item) => (
              <DimensionRow
                key={item.id}
                item={item}
                dimensions={view.dimensions}
                busy={busy || saving}
                onSelect={() => setSelected(item)}
                onChoose={(choice) => choose(item, choice)}
              />
            ))}
          </div>

          {selected && (
            <div className="evidence-source" data-testid="dimension-source">
              <h4>{selected.material_title} · version {selected.material_version}</h4>
              {!material && <p role="status">This material is not available.</p>}
              {material && stale && <p role="status">This material has changed; reload evidence.</p>}
              {material && !stale && parts && (
                <div className="evidence-passages">
                  {material.passages.map((passage) =>
                    passage.id === selected.passage_id ? (
                      <p key={passage.id} className="evidence-passage highlighted">
                        {parts.before}
                        <mark ref={markRef} data-testid="dimension-source-highlight">{parts.mark}</mark>
                        {parts.after}
                      </p>
                    ) : (
                      <p key={passage.id} className="evidence-passage">{passage.text}</p>
                    ),
                  )}
                </div>
              )}
            </div>
          )}

          {highlightedDimension && (
            <div className="evidence-source" data-testid="dimension-list-source">
              <h4>
                {view.list!.title} · version {view.list!.version} · paragraph {highlightedDimension.paragraph}
              </h4>
              {!listMaterial && <p role="status">The list material is not available.</p>}
              {listMaterial && (() => {
                const parts = highlightParts(
                  listMaterial.passages.find((p) => p.id === highlightedDimension.passage_id)?.text ?? '',
                  highlightedDimension.start,
                  highlightedDimension.end,
                )
                return (
                  <p className="evidence-passage highlighted">
                    {parts.before}
                    <mark ref={markRef} data-testid="dimension-list-highlight">{parts.mark}</mark>
                    {parts.after}
                  </p>
                )
              })()}
            </div>
          )}
        </>
      )}
    </section>
  )
}

function DimensionRow({
  item,
  dimensions,
  busy,
  onSelect,
  onChoose,
}: {
  item: EvidenceItem
  dimensions: DimensionsResponse['dimensions']
  busy: boolean
  onSelect: () => void
  onChoose: (choice: Parameters<typeof setEvidenceDimension>[2]) => void
}) {
  const selectValue =
    item.dim_set_by === 'clinician' && item.dimension_id
      ? item.dimension_id
      : item.dim_state === 'rejected'
        ? 'none'
        : ''
  return (
    <div className="dimension-row" data-testid="dimension-item">
      <button type="button" className="evidence-item" disabled={busy} onClick={onSelect}>
        <span className="evidence-quote">{item.quote}</span>
        <span className="evidence-chips">
          <span className="evidence-chip role-chip">From: {item.role_label || roleLabel(item.role)}</span>
          <span className="evidence-chip dimension-chip" data-testid="dimension-chip">
            {dimensionChipLabel(item)}
          </span>
        </span>
        <span className="evidence-source-line">
          {item.material_title} · paragraph {item.paragraph}
        </span>
        <span className="evidence-reason" data-testid="dimension-reason">{reasonLine(item.dim_reason)}</span>
      </button>
      <div className="evidence-choice-controls">
        {canConfirm(item) && (
          <button
            type="button"
            className="secondary-button"
            disabled={busy}
            onClick={() => onChoose({ action: 'confirm' })}
          >
            Confirm mapping
          </button>
        )}
        <label className="evidence-choice">
          Change dimension
          <select
            aria-label="Change dimension"
            value={selectValue}
            disabled={busy}
            onChange={(event) => {
              const value = event.target.value
              if (value === '') return
              if (value === 'none') onChoose({ action: 'none' })
              else onChoose({ dimension_id: value })
            }}
          >
            <option value="">Change to…</option>
            {dimensions.map((dimension) => (
              <option key={dimension.id} value={dimension.id}>{dimension.name}</option>
            ))}
            <option value="none">{NO_DIMENSION_LABEL}</option>
          </select>
        </label>
        {canReject(item) && (
          <button
            type="button"
            className="ghost-button"
            disabled={busy}
            onClick={() => onChoose({ action: 'none' })}
          >
            Wrong, no dimension
          </button>
        )}
      </div>
    </div>
  )
}

/** Empty-state upload button: uploads a dims-kind material picked by her. */
function UploadListButton({
  workspaceId,
  disabled,
  onUploaded,
}: {
  workspaceId: string
  disabled: boolean
  onUploaded: () => void
}) {
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function handleFile(file: File) {
    setBusy(true)
    setError('')
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('material_id', `dims-${Date.now()}`)
      form.append('title', file.name.replace(/\.[^.]+$/, ''))
      form.append('provider', 'clinician upload')
      form.append('date', new Date().toISOString().slice(0, 10))
      await uploadMaterialWithKind(workspaceId, form, 'dims')
      onUploaded()
    } catch {
      setError('Could not upload the dimension list. Check the file and try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <input
        ref={fileRef}
        type="file"
        accept=".txt,.md"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) void handleFile(file)
          event.target.value = ''
        }}
      />
      <button
        type="button"
        className="primary-button"
        disabled={disabled || busy}
        onClick={() => fileRef.current?.click()}
      >
        Upload dimension list
      </button>
      {error && <p className="error-banner" role="alert">{error}</p>}
    </div>
  )
}
