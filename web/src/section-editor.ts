// R9 (PT-11): section-editor state transitions, kept pure so the UI rules are
// unit-testable. Clinician-authored sections never accept generated text.

import { draftFilterBlocked } from './citecheck'
import { isClinicianAuthoredSection } from './sections'
import type { DraftSentence, SectionState, SectionStatus, TemplateSection } from './types'

export interface EditorDraft {
  text: string
  status: SectionStatus
  reviewer: string
  claimIds: string[]
  sentences: DraftSentence[]
}

export const CLINICIAN_AUTHORED_NOTICE =
  'You write this section. Clinical impressions and recommendations are never sent to the AI assistant, '
  + 'are never auto-filled, and never receive a diagnostic conclusion from the model.'

export const CLINICIAN_AUTHORED_EMPTY = 'You write this'

export function draftFromSectionState(
  initial: Pick<SectionState, 'text' | 'status' | 'reviewer' | 'claim_ids' | 'sentences'>,
): EditorDraft {
  return {
    text: initial.text,
    status: initial.status,
    reviewer: initial.reviewer ?? '',
    claimIds: [...initial.claim_ids],
    sentences: [...(initial.sentences ?? [])],
  }
}

/** True when this section uses prepare -> approve -> send. */
export function sectionUsesGeneration(section: TemplateSection): boolean {
  return !isClinicianAuthoredSection(section)
}

/** False when generated text must not land: clinician-authored or filtered. */
export function canApplyGeneratedText(
  section: TemplateSection,
  text: string,
  uploadedTexts: readonly string[] = [],
): boolean {
  if (isClinicianAuthoredSection(section)) return false
  return !draftFilterBlocked(section, text, uploadedTexts).blocked
}


/** The save bar's persistent state label (R9-AC1). */
export function saveStateLabel(dirty: boolean): 'Unsaved changes' | 'Saved' {
  return dirty ? 'Unsaved changes' : 'Saved'
}

function statusAfterEdit(status: SectionStatus, text: string): SectionStatus {
  if (status === 'approved') return 'draft'
  if (status === 'empty' && text.trim() !== '') return 'draft'
  return status
}

/** Apply generated text, except for sections only the clinician may write. */
export function applyGeneratedText(
  section: TemplateSection,
  draft: EditorDraft,
  text: string,
  claimIds: string[],
): EditorDraft {
  if (isClinicianAuthoredSection(section)) return draft
  return { ...draft, text, claimIds: [...claimIds], status: 'draft', reviewer: '', sentences: [] }
}

const SENTENCE_SPLIT = /(?<=[.!?。！？])\s+/

/** Split draft text into sentences for an unverified fallback. */
export function splitDraftSentences(text: string): string[] {
  const trimmed = text.trim()
  if (trimmed === '') return []
  const parts = trimmed.split(SENTENCE_SPLIT).map((part) => part.trim()).filter((part) => part !== '')
  return parts.length > 0 ? parts : [trimmed]
}

/** Mark every sentence Unverified when citation checking could not run. */
export function unverifiedSentencesFromText(sectionId: string, text: string): DraftSentence[] {
  return splitDraftSentences(text).map((sentenceText, index) => ({
    sentence_id: `sent_fallback_${sectionId}_${index}`,
    ordinal: index + 1,
    text: sentenceText,
    evidence_ids: [],
    state: 'unverified' as const,
  }))
}

/** Land generated text after a citecheck transport or 5xx failure: keep the text, mark Unverified. */
export function applyUnverifiedGeneratedText(
  section: TemplateSection,
  draft: EditorDraft,
  text: string,
  claimIds: string[],
): EditorDraft {
  const applied = applyGeneratedText(section, draft, text, claimIds)
  if (applied === draft) return draft
  return applySentences(applied, unverifiedSentencesFromText(section.id, text))
}

export const CITECHECK_FAILURE_MESSAGE =
  'Could not check citations for this draft. The generated text was kept as Unverified.'

export function editDraftText(draft: EditorDraft, text: string): EditorDraft {
  return { ...draft, text, status: statusAfterEdit(draft.status, text), sentences: [] }
}

export function toggleDraftClaim(draft: EditorDraft, claimId: string): EditorDraft {
  const claimIds = draft.claimIds.includes(claimId)
    ? draft.claimIds.filter((value) => value !== claimId)
    : [...draft.claimIds, claimId]
  return { ...draft, claimIds, status: draft.status === 'approved' ? 'draft' : draft.status }
}

export function setDraftStatus(draft: EditorDraft, status: SectionStatus): EditorDraft {
  return { ...draft, status }
}

export type SaveBarPrimary = 'approve' | 'save' | null

/** Whether Approve section can run: saved text, not already approved, reviewer if required. */
export function canApproveSection(
  draft: EditorDraft,
  reviewGate: TemplateSection['review_gate'],
): boolean {
  if (draft.status === 'approved') return false
  if (draft.text.trim() === '') return false
  if (reviewGate === 'licensed_clinician' && draft.reviewer.trim() === '') return false
  return true
}

/**
 * One primary action in the draft save bar (prototype rule, M1 / Q7 has no Export).
 * When the send pane has a step to take, the save bar carries no primary —
 * Approve request or Send once in the egress panel is the view's primary.
 * Otherwise: Approve section when it can run, else Save when there are unsaved edits.
 */
export function saveBarPrimaryAction(options: {
  dirty: boolean
  canApprove: boolean
  sendStepActive: boolean
}): SaveBarPrimary {
  if (options.sendStepActive) return null
  if (!options.dirty && options.canApprove) return 'approve'
  if (options.dirty) return 'save'
  return null
}

/** True when the egress panel's current step is the view's primary. */
export function egressPrimaryStepActive(
  phase: string,
  approvalReady: boolean,
  locked: boolean,
): boolean {
  if (phase === 'prepared') return approvalReady && !locked
  if (phase === 'approving' || phase === 'sending') return true
  if (phase === 'approved') return !locked
  return false
}

export function applySentences(draft: EditorDraft, sentences: DraftSentence[]): EditorDraft {
  return { ...draft, sentences: [...sentences] }
}

export function textFromSentences(sentences: DraftSentence[]): string {
  return sentences.map((sentence) => sentence.text).join(' ')
}

export function markSentenceJudgment(
  draft: EditorDraft,
  sentenceId: string,
  judged: boolean,
): EditorDraft {
  const sentences = draft.sentences.map((sentence) => {
    if (sentence.sentence_id !== sentenceId) return sentence
    if (judged) return { ...sentence, state: 'my_judgment' as const }
    return { ...sentence, state: sentence.evidence_ids.length ? 'needs_review' as const : 'unverified' as const }
  })
  return { ...draft, sentences }
}
