import { useEffect, useRef, useState } from 'react'
import { getEvidence } from '../api'
import { droppedNotice, evidenceSourceLine, highlightParts } from '../evidence'
import type { EvidenceItem, EvidenceResponse, Material } from '../types'

const HEADER_TEXT =
  "Each item is one sentence from this case's materials. Click an item to see where it comes from. This list is for you to check; it is not a conclusion."

const STALE_MATERIAL_MESSAGE = 'This material has changed; reload evidence.'

interface EvidencePanelProps {
  workspaceId: string
  materials: Material[]
  busy: boolean
}

export default function EvidencePanel({ workspaceId, materials, busy }: EvidencePanelProps) {
  const [evidence, setEvidence] = useState<EvidenceResponse | null>(null)
  const [selected, setSelected] = useState<EvidenceItem | null>(null)
  const [error, setError] = useState('')
  const lifecycle = useRef<symbol | null>(null)

  useEffect(() => {
    lifecycle.current = Symbol()
    return () => { lifecycle.current = null }
  }, [])

  // Reload whenever the workspace (or its materials) changes; ignore stale
  // responses after unmount/case switch, like the other panels do.
  useEffect(() => {
    const current = lifecycle.current
    if (current === null) return
    let active = true
    setSelected(null)
    getEvidence(workspaceId)
      .then((response) => {
        if (!active || lifecycle.current !== current) return
        setEvidence(response)
        setError('')
      })
      .catch(() => {
        if (!active || lifecycle.current !== current) return
        setEvidence(null)
        setError('Could not load evidence. Reload to try again.')
      })
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
            <li key={item.id}>
              <button
                type="button"
                className="evidence-item"
                data-testid="evidence-item"
                aria-pressed={selected?.id === item.id}
                disabled={busy}
                onClick={() => setSelected(item)}
              >
                <span className="evidence-quote">{item.quote}</span>
                <span className="evidence-source-line">
                  {evidenceSourceLine(item.material_title, item.material_version, item.paragraph)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {evidence && droppedNotice(evidence.dropped) && (
        <p className="dropped-notice" role="status">{droppedNotice(evidence.dropped)}</p>
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
