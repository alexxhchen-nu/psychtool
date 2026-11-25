import { useEffect, useRef, useState } from 'react'
import { getEvidence, refreshEvidence, setEvidenceChoice } from '../api'
import { droppedNotice, highlightParts } from '../evidence'
import { correctionToast } from '../correction'
import type { EvidenceInvalidation, EvidenceItem, EvidenceResponse, Material } from '../types'
import EvidenceRow from './EvidenceRow'

const HEADER_TEXT =
  "Each item is one sentence from this case's materials. Click an item to see where it comes from. This list is for you to check; it is not a conclusion."

const STALE_MATERIAL_MESSAGE = 'This material has changed; reload evidence.'

interface EvidencePanelProps {
  workspaceId: string
  materials: Material[]
  busy: boolean
  /** R6 (PT-09 / ADR 0018): the case-level toast + pill/revision updater. */
  onCorrection?: (toast: string, invalidation: EvidenceInvalidation) => void
  /** PT-10: open this item in the right-column source card. */
  onOpenSource?: (item: EvidenceItem) => void
}

export default function EvidencePanel({ workspaceId, materials, busy, onCorrection, onOpenSource }: EvidencePanelProps) {
  const [evidence, setEvidence] = useState<EvidenceResponse | null>(null)
  const [selected, setSelected] = useState<EvidenceItem | null>(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [dropped, setDropped] = useState(0)
  const lifecycle = useRef<symbol | null>(null)

  useEffect(() => {
    lifecycle.current = Symbol()
    return () => { lifecycle.current = null }
  }, [])

  // Reload whenever the workspace (or its materials) changes; ignore stale
  // responses after unmount/case switch, like the other panels do. When the
  // server says the latest material versions have no evidence rows yet
  // (needs_extraction), run one refresh first, then load (ADR 0015).
  useEffect(() => {
    const current = lifecycle.current
    if (current === null) return
    let active = true
    setSelected(null)
    setDropped(0)
    const stale = () => !active || lifecycle.current !== current
    ;(async () => {
      try {
        let response = await getEvidence(workspaceId)
        if (stale()) return
        if (response.needs_extraction) {
          const summary = await refreshEvidence(workspaceId)
          if (stale()) return
          setDropped(summary.dropped)
          response = await getEvidence(workspaceId)
          if (stale()) return
        }
        setEvidence(response)
        setError('')
      } catch {
        if (stale()) return
        setEvidence(null)
        setError('Could not load evidence. Reload to try again.')
      }
    })()
    return () => { active = false }
  }, [workspaceId, materials])

  const markRef = useRef<HTMLElement | null>(null)
  useEffect(() => {
    markRef.current?.scrollIntoView({ block: 'center' })
  }, [selected])

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

  // Her category/role choice: PUT, then reload the list so chips, reasons and
  // the selected item reflect what the server persisted (R5 / ADR 0015).
  // R6 (PT-09): the response carries the same-transaction invalidation; the
  // server's toast is surfaced verbatim and the case-level callback updates
  // section pills / egress revision without touching unsaved editor text.
  async function choose(item: EvidenceItem, choice: { category?: EvidenceItem['category'] | null; role?: EvidenceItem['role'] | null }) {
    const current = lifecycle.current
    if (current === null || saving) return
    setSaving(true)
    try {
      const result = await setEvidenceChoice(workspaceId, item.id, choice)
      if (lifecycle.current !== current) return
      const toast = correctionToast(result)
      if (toast && result.invalidation) onCorrection?.(toast, result.invalidation)
      const response = await getEvidence(workspaceId)
      if (lifecycle.current !== current) return
      setEvidence(response)
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

  return (
    <section className="names-panel evidence-panel" aria-label="Evidence">
      <div className="names-panel-copy">
        <h3>Evidence.</h3>
        <p>{HEADER_TEXT}</p>
      </div>
      {error && <p className="error-banner" role="alert">{error}</p>}
      {evidence && evidence.items.length === 0 && !error && (
        <p role="status">No evidence in this case yet.</p>
      )}
      {evidence && evidence.items.length > 0 && (
        <ul className="evidence-list">
          {evidence.items.map((item) => (
            <EvidenceRow
              key={item.id}
              item={item}
              selected={selected?.id === item.id}
              busy={busy}
              saving={saving}
              onSelect={setSelected}
              onOpenSource={(row) => onOpenSource?.(row)}
              onChoose={choose}
            />
          ))}
        </ul>
      )}
      {droppedNotice(dropped) && (
        <p className="dropped-notice" role="status">{droppedNotice(dropped)}</p>
      )}
      {selected && (
        <div className="evidence-source" data-testid="evidence-source">
          <h4>{selected.material_title} · version {selected.material_version}</h4>
          {!material && <p role="status">This material is not available.</p>}
          {material && stale && <p role="status">{STALE_MATERIAL_MESSAGE}</p>}
          {material && !stale && parts && (
            <div className="evidence-passages">
              {material.passages.map((passage) =>
                passage.id === selected.passage_id ? (
                  <p key={passage.id} className="evidence-passage highlighted">
                    {parts.before}
                    <mark ref={markRef} data-testid="evidence-highlight">{parts.mark}</mark>
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
    </section>
  )
}
