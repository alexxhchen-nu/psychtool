import type { SourceCardModel, StatusTagStyle } from '../source-card'
import { SOURCE_LOCATION_NOTE, STATUS_TAG, sourceLocationLine } from '../source-card'

export function StatusTag({ status }: { status: StatusTagStyle }) {
  return (
    <span className={`tag ${status.className}`} data-testid="source-status">
      <span aria-hidden="true">{status.glyph}</span>
      {status.label}
    </span>
  )
}

interface SourceCardProps {
  card: SourceCardModel
  onClose: () => void
}

/**
 * The right-column source card. It is ordinary page content (never a dialog
 * or overlay), so the middle editor stays mounted and editable behind it.
 */
export default function SourceCard({ card, onClose }: SourceCardProps) {
  const tag = STATUS_TAG[card.confirmation]
  const location = sourceLocationLine(card)
  return (
    <section className="source-card" aria-label="Source details" data-testid="source-card">
      <div className="source-card-head">
        <span className="source-kind">{card.kind === 'evidence' ? 'Evidence' : 'Claim'}</span>
        <button type="button" className="source-close" onClick={onClose}>Close source</button>
      </div>
      <StatusTag status={tag} />
      <p className="field-label source-quote-label">Quoted passage</p>
      <blockquote className="source-quote">{card.quote}</blockquote>
      <dl className="source-meta">
        {card.materialTitle && (
          <div><dt>Material</dt><dd>{card.materialTitle}</dd></div>
        )}
        {card.materialVersion != null && (
          <div><dt>Version</dt><dd>{card.materialVersion}</dd></div>
        )}
        {card.providerRole && (
          <div><dt>Source role</dt><dd>{card.providerRole}</dd></div>
        )}
        <div><dt>Source ID</dt><dd>{card.id}</dd></div>
      </dl>
      {location && (
        <p className="source-location" data-testid="source-location">{location}</p>
      )}
      <p className="source-note">{SOURCE_LOCATION_NOTE}</p>
    </section>
  )
}
