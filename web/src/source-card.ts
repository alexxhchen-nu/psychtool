// PT-10: the right-column source card is a presentation model. Every field is
// copied from the server response or from a material already loaded for the
// case; nothing here invents a location (no page numbers, no guessed spans).

import { evidenceSourceLine, roleLabel } from './evidence'
import type { Claim, EvidenceItem, Material } from './types'

export type SourceKind = 'evidence' | 'claim'
export type SourceConfirmation = 'verified' | 'needs_review' | 'unverified'

export interface SourceCardModel {
  kind: SourceKind
  id: string
  quote: string
  /** Present only when the case knows the material's title. */
  materialTitle: string | null
  /** Present only when the case knows the material version. */
  materialVersion: number | null
  /** Present only for evidence rows that recorded a paragraph. */
  paragraph: number | null
  /** Store offsets are 0-based half-open [start, end); rendered 1-based. */
  start: number | null
  end: number | null
  /** Human label for the source role, or null when it is unknown. */
  providerRole: string | null
  confirmation: SourceConfirmation
}

export interface StatusTagStyle {
  className: 'ok' | 'chk' | 'un'
  glyph: string
  label: string
}

export const STATUS_TAG: Record<SourceConfirmation, StatusTagStyle> = {
  verified: { className: 'ok', glyph: '✓', label: 'Verified' },
  needs_review: { className: 'chk', glyph: '?', label: 'Needs review' },
  unverified: { className: 'un', glyph: '!', label: 'Unverified' },
}

export const SOURCE_LOCATION_NOTE =
  'Only locations recorded in the case are shown. No page number is inferred.'

const CLAIM_PROVIDER_LABELS: Record<string, string> = {
  self_report: 'Self report',
  other_report: 'Other report',
  clinician_interpretation: 'Clinician interpretation',
}

/** Evidence stays unconfirmed until the clinician has confirmed its mapping
 * and both category and role, or explicitly rejected it. */
export function evidenceConfirmation(item: EvidenceItem): SourceConfirmation {
  if (item.dim_state === 'rejected') return 'unverified'
  if (
    item.dim_state === 'confirmed' ||
    (item.category_set_by === 'clinician' && item.role_set_by === 'clinician')
  ) {
    return 'verified'
  }
  return 'needs_review'
}

/** Claims are pending until the clinician verified them; a viewed conflict
 * remains a warning rather than a verification. */
export function claimConfirmation(claim: Claim): SourceConfirmation {
  if (claim.verification_status === 'verified') return 'verified'
  if (claim.verification_status === 'conflict-viewed') return 'unverified'
  return 'needs_review'
}

export function sourceCardFromEvidence(item: EvidenceItem): SourceCardModel {
  return {
    kind: 'evidence',
    id: item.id,
    quote: item.quote,
    materialTitle: item.material_title || null,
    materialVersion: item.material_version ?? null,
    paragraph: item.paragraph ?? null,
    start: item.start ?? null,
    end: item.end ?? null,
    providerRole: item.role_label || roleLabel(item.role) || null,
    confirmation: evidenceConfirmation(item),
  }
}

export function sourceCardFromClaim(
  claim: Claim,
  materials: Material[],
): SourceCardModel {
  const material = materials.find((item) => item.id === claim.source_document_id)
  const passage = material?.passages.find(
    (item) => item.id === claim.source_passage_id,
  )
  return {
    kind: 'claim',
    id: claim.id,
    quote: passage?.text ?? claim.text,
    materialTitle: material?.title || claim.source_document_id || null,
    materialVersion: claim.source_version ?? null,
    paragraph: null,
    start: null,
    end: null,
    providerRole:
      CLAIM_PROVIDER_LABELS[claim.provider_role] ?? claim.provider_role ?? null,
    confirmation: claimConfirmation(claim),
  }
}

/** The card's location line; missing parts are omitted, never guessed. */
export function sourceLocationLine(card: SourceCardModel): string {
  return evidenceSourceLine(
    card.materialTitle,
    card.materialVersion,
    card.paragraph,
    card.start,
    card.end,
  )
}
