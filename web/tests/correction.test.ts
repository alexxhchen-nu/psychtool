import { describe, expect, test } from 'bun:test'
import {
  applyInvalidationToSections,
  correctionToast,
  hasCascade,
} from '../src/correction'
import type { EvidenceInvalidation, SectionState } from '../src/types'

// PT-09 chunk 3 (R6 / ADR 0018): the client renders the server's toast
// VERBATIM and never invents counts; section pills may flip to Needs review
// but text is never touched.

const NO_CASCADE_TOAST =
  'Your change was saved. 0 sections were returned to Needs review. Unsaved text was not changed.'

function invalidation(overrides: Partial<EvidenceInvalidation> = {}): EvidenceInvalidation {
  return { claims: [], sections: [], egress: [], toast: NO_CASCADE_TOAST, ...overrides }
}

function section(overrides: Partial<SectionState> = {}): SectionState {
  return {
    section_id: 'history',
    title: 'History',
    status: 'approved',
    review_gate: 'standard',
    required: true,
    text: 'Saved section text.',
    claim_ids: ['c1'],
    version: 3,
    reviewer: 'Dr. Synthetic',
    ...overrides,
  }
}

describe('correctionToast', () => {
  test('returns the exact server string for a zero-count (no cascade) toast', () => {
    expect(correctionToast({ invalidation: invalidation() })).toBe(NO_CASCADE_TOAST)
  })

  test('returns the exact server string for singular counts', () => {
    const toast =
      'Your change was saved. 1 citing statement is no longer marked verified. ' +
      '1 section was returned to Needs review. ' +
      '1 prepared request was invalidated and must be prepared again. ' +
      'Unsaved text was not changed.'
    expect(correctionToast({ invalidation: invalidation({ toast }) })).toBe(toast)
  })

  test('returns the exact server string for plural counts', () => {
    const toast =
      'Your change was saved. 2 citing statements are no longer marked verified. ' +
      '3 sections were returned to Needs review. ' +
      '2 prepared requests were invalidated and must be prepared again. ' +
      'Unsaved text was not changed.'
    expect(correctionToast({ invalidation: invalidation({ toast }) })).toBe(toast)
  })

  test('returns null when the response carries no toast', () => {
    expect(correctionToast(null)).toBeNull()
    expect(correctionToast(undefined)).toBeNull()
    expect(correctionToast({})).toBeNull()
    expect(correctionToast({ invalidation: invalidation({ toast: '' }) })).toBeNull()
  })
})

describe('hasCascade', () => {
  test('is false for empty lists (role-only / no-op responses)', () => {
    expect(hasCascade(invalidation())).toBe(false)
    expect(hasCascade(null)).toBe(false)
    expect(hasCascade(undefined)).toBe(false)
  })

  test('is true when any list is non-empty', () => {
    expect(hasCascade(invalidation({ claims: ['c1'] }))).toBe(true)
    expect(hasCascade(invalidation({ sections: ['history'] }))).toBe(true)
    expect(hasCascade(invalidation({ egress: ['req-1'] }))).toBe(true)
  })
})

describe('applyInvalidationToSections', () => {
  test('flips only the listed approved sections to needs_review', () => {
    const sections = [
      section(),
      section({ section_id: 'client_details', title: 'Client Details' }),
      section({ section_id: 'methods', title: 'Methods', status: 'draft' }),
    ]
    const next = applyInvalidationToSections(
      sections,
      invalidation({ sections: ['history'] }),
    )
    expect(next[0].status).toBe('needs_review')
    // Unlisted sections keep their state, drafts are left alone.
    expect(next[1].status).toBe('approved')
    expect(next[2].status).toBe('draft')
  })

  test('never rewrites text, claim ids, reviewer or version', () => {
    const before = section()
    const [after] = applyInvalidationToSections(
      [before],
      invalidation({ sections: ['history'] }),
    )
    expect(after.text).toBe('Saved section text.')
    expect(after.claim_ids).toEqual(['c1'])
    expect(after.reviewer).toBe('Dr. Synthetic')
    expect(after.version).toBe(3)
    expect(after.status).toBe('needs_review')
  })

  test('a section already back at draft (unsaved edits) is not re-flagged', () => {
    // She typed after approving: the local pill already left approved, so the
    // helper must not fight her in-progress state.
    const before = section({ status: 'draft' })
    const [after] = applyInvalidationToSections(
      [before],
      invalidation({ sections: ['history'] }),
    )
    expect(after).toBe(before)
  })

  test('returns the same array when nothing was invalidated', () => {
    const sections = [section()]
    expect(applyInvalidationToSections(sections, invalidation())).toBe(sections)
    expect(applyInvalidationToSections(sections, null)).toBe(sections)
  })
})
