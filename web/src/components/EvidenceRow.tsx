import {
  CATEGORY_OPTIONS,
  ROLE_OPTIONS,
  categoryLabel,
  evidenceSourceLine,
  reasonLine,
  roleLabel,
  setByText,
} from '../evidence'
import { dimensionChipLabel } from '../dimensions'
import { STATUS_TAG, evidenceConfirmation } from '../source-card'
import type { EvidenceItem } from '../types'
import { StatusTag } from './SourceCard'

export interface EvidenceRowProps {
  item: EvidenceItem
  selected: boolean
  busy: boolean
  saving: boolean
  onSelect: (item: EvidenceItem) => void
  onOpenSource: (item: EvidenceItem) => void
  onChoose: (
    item: EvidenceItem,
    choice: { category?: EvidenceItem['category'] | null; role?: EvidenceItem['role'] | null },
  ) => void
}

/** One evidence row. Exported so the click-to-source wiring can be tested. */
export default function EvidenceRow({
  item,
  selected,
  busy,
  saving,
  onSelect,
  onOpenSource,
  onChoose,
}: EvidenceRowProps) {
  return (
    <li>
      <button
        type="button"
        className="evidence-item"
        data-testid="evidence-item"
        aria-pressed={selected}
        disabled={busy}
        onClick={() => {
          onSelect(item)
          onOpenSource(item)
        }}
      >
        <span className="evidence-quote">{item.quote}</span>
        <StatusTag status={STATUS_TAG[evidenceConfirmation(item)]} />
        <span className="evidence-chips">
          <span
            className={`evidence-chip category-chip${item.category === 'uncategorized' ? ' uncategorized' : ''}`}
            data-testid="category-chip"
          >
            {item.category_label || categoryLabel(item.category)}
          </span>
          <span className="evidence-chip role-chip" data-testid="role-chip">
            From: {item.role_label || roleLabel(item.role)}
          </span>
          <span className="evidence-chip dimension-chip" data-testid="dimension-chip">
            Dimension: {dimensionChipLabel(item)}
          </span>
        </span>
        <span className="evidence-reason" data-testid="category-reason">
          {reasonLine(item.category_reason)}
        </span>
        {setByText(item.category_set_by) && (
          <span className="evidence-set-by">{setByText(item.category_set_by)}</span>
        )}
        {setByText(item.role_set_by) && (
          <span className="evidence-set-by">{setByText(item.role_set_by)}</span>
        )}
        <span className="evidence-source-line">
          {evidenceSourceLine(
            item.material_title,
            item.material_version,
            item.paragraph,
            item.start,
            item.end,
          )}
        </span>
      </button>
      <div className="evidence-choice-controls">
        <label className="evidence-choice">
          Change category
          <select
            aria-label="Change category"
            value={item.category}
            disabled={busy || saving}
            onChange={(event) => onChoose(item, { category: event.target.value as EvidenceItem['category'] })}
          >
            {CATEGORY_OPTIONS.map((option) => (
              <option key={option.key} value={option.key}>{option.label}</option>
            ))}
          </select>
        </label>
        <label className="evidence-choice">
          Change source role
          <select
            aria-label="Change source role"
            value={item.role}
            disabled={busy || saving}
            onChange={(event) => onChoose(item, { role: event.target.value as EvidenceItem['role'] })}
          >
            {ROLE_OPTIONS.map((option) => (
              <option key={option.key} value={option.key}>{option.label}</option>
            ))}
          </select>
        </label>
      </div>
    </li>
  )
}
