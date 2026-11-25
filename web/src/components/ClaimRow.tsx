import type { Claim } from '../types'
import { STATUS_TAG, claimConfirmation } from '../source-card'
import { StatusTag } from './SourceCard'

export interface ClaimRowProps {
  claim: Claim
  checked: boolean
  busy: boolean
  onToggle: (id: string) => void
  onOpenSource: (claim: Claim) => void
}

/** One selectable source claim. The text opens the source card; the checkbox
 * only attaches or detaches the claim. Exported for click-wiring tests. */
export default function ClaimRow({
  claim,
  checked,
  busy,
  onToggle,
  onOpenSource,
}: ClaimRowProps) {
  return (
    <li>
      <div className="claim-row">
        <input
          type="checkbox"
          disabled={busy}
          checked={checked}
          aria-label={`Use ${claim.id} as a source: ${claim.text}`}
          onChange={() => onToggle(claim.id)}
        />
        <span className="claim-id">{claim.id}</span>
        <button
          type="button"
          className="claim-text claim-source"
          data-testid="claim-source"
          disabled={busy}
          onClick={() => onOpenSource(claim)}
        >
          <StatusTag status={STATUS_TAG[claimConfirmation(claim)]} />
          <span>{claim.text}</span>
        </button>
      </div>
    </li>
  )
}
