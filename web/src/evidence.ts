// PT-06 (R4): pure evidence helpers. Offsets from the server are Unicode
// code-point indices into a passage's text (see ADR 0014); JavaScript string
// slicing is UTF-16 based, so everything here goes through Array.from to
// keep Python and the browser in agreement even with astral characters.

import type { EvidenceCategory, EvidenceRole } from './types'

export interface HighlightParts {
  before: string
  mark: string
  after: string
}

/**
 * Split `text` around the code-point range [start, end) so the mark slice
 * equals `Array.from(text).slice(start, end).join('')`.
 */
export function highlightParts(text: string, start: number, end: number): HighlightParts {
  const codePoints = Array.from(text)
  const safeStart = Math.max(0, Math.min(start, codePoints.length))
  const safeEnd = Math.max(safeStart, Math.min(end, codePoints.length))
  return {
    before: codePoints.slice(0, safeStart).join(''),
    mark: codePoints.slice(safeStart, safeEnd).join(''),
    after: codePoints.slice(safeEnd).join(''),
  }
}

/** Format the source line shown under each evidence quote. */
export function evidenceSourceLine(materialTitle: string, version: number, paragraph: number): string {
  return `${materialTitle} · version ${version} · paragraph ${paragraph}`
}

/** Fixed notice shown only when candidates were dropped (never repaired). */
export function droppedNotice(dropped: number): string | null {
  if (dropped <= 0) return null
  const noun = dropped === 1 ? 'candidate was' : 'candidates were'
  return `${dropped} ${noun} dropped because the quote did not match the source exactly.`
}

// -- R5 (PT-07 / ADR 0015): category & source-role presentation --------------
//
// Labels mirror psychtool/core/categorize.py exactly; the server sends the
// label with each item, and these helpers only provide the select options
// and the fallback for a key the server did not label.

export const CATEGORY_OPTIONS: { key: EvidenceCategory; label: string }[] = [
  { key: 'family_history', label: 'Family history' },
  { key: 'medical_history', label: 'Medical history' },
  { key: 'test_results', label: 'Test results' },
  { key: 'behavioral_observations', label: 'Behavioral observations' },
  { key: 'development_school', label: 'Development & school' },
  { key: 'daily_living', label: 'Daily living & function' },
  { key: 'other', label: 'Other' },
  { key: 'uncategorized', label: 'Uncategorized' },
]

export const ROLE_OPTIONS: { key: EvidenceRole; label: string }[] = [
  { key: 'school', label: 'School' },
  { key: 'caregiver', label: 'Caregiver' },
  { key: 'medical_record', label: 'Medical record' },
  { key: 'clinician', label: 'Clinician' },
  { key: 'client', label: 'Client' },
  { key: 'to_confirm', label: 'To confirm' },
]

/** Label for a category key; unknown keys pass through verbatim. */
export function categoryLabel(key: EvidenceCategory): string {
  return CATEGORY_OPTIONS.find((option) => option.key === key)?.label ?? key
}

/** Label for a source-role key; unknown keys pass through verbatim. */
export function roleLabel(key: EvidenceRole): string {
  return ROLE_OPTIONS.find((option) => option.key === key)?.label ?? key
}

/** "From: {label}" line under each evidence quote (R5). */
export function roleLine(role: EvidenceRole): string {
  return `From: ${roleLabel(role)}`
}

/** Shown when the server's reason is empty (never for default rules). */
export const NO_REASON_TEXT = 'No reason recorded.'

/** Reason line for a category suggestion (R5-AC1; full text, no clamp). */
export function reasonLine(reason: string): string {
  return `Why: ${reason || NO_REASON_TEXT}`
}

/** Marks her own choices so she can tell them from suggestions. */
export function setByText(setBy: 'clinician' | 'suggestion'): string | null {
  return setBy === 'clinician' ? 'Set by you' : null
}
