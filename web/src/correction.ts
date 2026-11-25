// PT-09 chunk 3 (R6 / ADR 0018): pure helpers for the correction toast.
//
// The server computes the toast string and the invalidated id lists in the
// same transaction as her correction; the client renders the toast VERBATIM
// and never invents counts. These helpers only decide which open section
// pills may flip to Needs review (status only — never text).

import type { EvidenceInvalidation, SectionState } from './types'

/** The server's exact toast, or null when the response carried none. */
export function correctionToast(
  result: { invalidation?: EvidenceInvalidation } | null | undefined,
): string | null {
  const toast = result?.invalidation?.toast
  return typeof toast === 'string' && toast.length > 0 ? toast : null
}

/** True when the correction actually invalidated something. */
export function hasCascade(invalidation: EvidenceInvalidation | null | undefined): boolean {
  if (!invalidation) return false
  return (
    invalidation.claims.length > 0 ||
    invalidation.sections.length > 0 ||
    invalidation.egress.length > 0
  )
}

/**
 * Apply an R6 invalidation to the loaded section states: an open APPROVED
 * section the server returned to needs_review gets its status pill updated.
 * Text, claim ids, reviewer and version are untouched — unsaved editor text
 * is never rewritten by a correction. Sections not listed keep their state.
 */
export function applyInvalidationToSections(
  sections: SectionState[],
  invalidation: EvidenceInvalidation | null | undefined,
): SectionState[] {
  if (!invalidation || invalidation.sections.length === 0) return sections
  const affected = new Set(invalidation.sections)
  return sections.map((section) =>
    affected.has(section.section_id) && section.status === 'approved'
      ? { ...section, status: 'needs_review' }
      : section,
  )
}
