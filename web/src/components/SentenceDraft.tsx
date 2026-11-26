import type { DraftSentence } from '../types'

const STATE_LABEL: Record<DraftSentence['state'], string> = {
  verified: 'Verified',
  needs_review: 'Needs review',
  unverified: 'Unverified · no source found',
  my_judgment: 'My judgment',
}

const TAG_CLASS: Record<DraftSentence['state'], string> = {
  verified: 'ok',
  needs_review: 'chk',
  unverified: 'un',
  my_judgment: 'chk',
}

interface SentenceDraftProps {
  sentences: DraftSentence[]
  selectedId: string | null
  disabled: boolean
  onSelect: (sentenceId: string) => void
  onCite: (sentenceId: string, evidenceId: string) => void
  onEdit: (sentenceId: string, text: string) => void
  onMarkJudgment: (sentenceId: string, judged: boolean) => void
}

export default function SentenceDraft({
  sentences,
  selectedId,
  disabled,
  onSelect,
  onCite,
  onEdit,
  onMarkJudgment,
}: SentenceDraftProps) {
  const selected = sentences.find((sentence) => sentence.sentence_id === selectedId) ?? null
  const citeNumbers = new Map<string, number>()
  let citeCursor = 0
  for (const sentence of sentences) {
    for (const evidenceId of sentence.evidence_ids) {
      if (!citeNumbers.has(evidenceId)) {
        citeCursor += 1
        citeNumbers.set(evidenceId, citeCursor)
      }
    }
  }
  return (
    <div className="sentence-draft" data-testid="sentence-draft">
      <div className="sentence-list">
        {sentences.map((sentence) => {
          const cites = sentence.evidence_ids
          return (
            <p className="sentence-line" key={sentence.sentence_id}>
              <span
                className={`sent st-${sentence.state}${selectedId === sentence.sentence_id ? ' sel' : ''}`}
                data-testid={`sentence-${sentence.state}`}
                data-sentence-id={sentence.sentence_id}
                data-act="selsent"
                role="textbox"
                aria-label={`Draft sentence (${STATE_LABEL[sentence.state]})`}
                contentEditable={disabled ? false : 'plaintext-only'}
                suppressContentEditableWarning
                spellCheck={false}
                onClick={() => onSelect(sentence.sentence_id)}
                onBlur={(event) => {
                  const next = event.currentTarget.textContent ?? ''
                  if (next !== sentence.text) onEdit(sentence.sentence_id, next)
                }}
              >
                {sentence.text}
              </span>
              {cites.map((evidenceId) => (
                <button
                  key={evidenceId}
                  type="button"
                  className="cite"
                  data-testid="sentence-cite"
                  data-evidence-id={evidenceId}
                  onClick={() => onCite(sentence.sentence_id, evidenceId)}
                >
                  [{citeNumbers.get(evidenceId)}]
                </button>
              ))}
              <span className={`tag ${TAG_CLASS[sentence.state]}`} contentEditable={false}>
                {STATE_LABEL[sentence.state]}
              </span>
            </p>
          )
        })}
      </div>
      <p className="sentence-legend">
        <span><span className="tag ok">Verified</span> you checked the source</span>
        <span><span className="tag chk">Needs review</span> has a source, not yet checked</span>
        <span><span className="tag un">Unverified</span> no source found in the materials</span>
        <span><span className="tag chk">My judgment</span> your professional judgment, not a material fact</span>
      </p>
      {selected?.state === 'unverified' && (
        <div className="sentence-actions">
          <p className="muted" data-testid="unverified-hint">
            This sentence has no source. Delete it, rewrite it to match the materials, or mark it as your professional judgment.
          </p>
          <button
            type="button"
            className="secondary-button"
            data-testid="mark-my-judgment"
            disabled={disabled}
            onClick={() => onMarkJudgment(selected.sentence_id, true)}
          >
            Mark as my judgment
          </button>
        </div>
      )}
      {selected?.state === 'my_judgment' && (
        <div className="sentence-actions">
          <button
            type="button"
            className="secondary-button"
            data-testid="unmark-my-judgment"
            disabled={disabled}
            onClick={() => onMarkJudgment(selected.sentence_id, false)}
          >
            Unmark “my judgment”
          </button>
        </div>
      )}
    </div>
  )
}
