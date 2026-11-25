// R7 (PT-08 / ADR 0016): pure dimension-mapping presentation helpers.
// Labels mirror the prototype chips exactly; the server sends names/reasons,
// these helpers only decide the chip text and group membership.

import type { DimensionEntry, DimensionState } from './types'

export const NOT_DX_TEXT = 'This is not a diagnosis. The diagnosis is yours.'

export const NO_DIMENSION_LABEL = 'No dimension'
export const NOT_MAPPED_GROUP = 'Not mapped or unsure'

/** One evidence item's dimension-facing shape (a subset of EvidenceItem). */
export interface DimensionLike {
  dimension_id: string | null
  dimension_name: string | null
  dim_state: DimensionState
  dim_set_by: 'clinician' | 'suggestion'
}

/**
 * Prototype chip text (data-testid `dimension-chip`):
 * `No dimension` | `Dimension · Needs review` | `{name} · Needs review` |
 * `{name} · Confirmed by you` | `{name}`.
 */
export function dimensionChipLabel(item: DimensionLike): string {
  if (item.dim_state === 'rejected') return NO_DIMENSION_LABEL
  if (!item.dimension_name) {
    return item.dim_state === 'needs_review'
      ? 'Dimension · Needs review'
      : NO_DIMENSION_LABEL
  }
  if (item.dim_state === 'needs_review') return `${item.dimension_name} · Needs review`
  if (item.dim_set_by === 'clinician') return `${item.dimension_name} · Confirmed by you`
  return item.dimension_name
}

/** Items grouped under one dimension, in list order. */
export function itemsForDimension<T extends DimensionLike>(
  items: T[],
  dimensionId: string,
): T[] {
  return items.filter(
    (item) => item.dimension_id === dimensionId && item.dim_state !== 'rejected',
  )
}

/** Header line above the groups: `{n} need review · {m} evidence items`. */
export function reviewSummaryLine(needsReview: number, total: number): string {
  const noun = needsReview === 1 ? 'needs review' : 'need review'
  return `${needsReview} ${noun} · ${total} evidence items`
}

/** Source link label for one dimension group. */
export function dimensionSourceLabel(paragraph: number): string {
  return `Source: your list, paragraph ${paragraph}`
}

/** "Confirm mapping" is shown when the item has a dimension and is not yet
 * confirmed by her. */
export function canConfirm(item: DimensionLike): boolean {
  return (
    Boolean(item.dimension_id) &&
    !(item.dim_state === 'confirmed' && item.dim_set_by === 'clinician')
  )
}

/** "Wrong, no dimension" is shown when the item has a dimension and is not
 * rejected. */
export function canReject(item: DimensionLike): boolean {
  return Boolean(item.dimension_id) && item.dim_state !== 'rejected'
}

/** Build the ordered group list: one per dimension, then the rest (the UI
 * renders the rest under "Not mapped or unsure"). */
export function buildGroups<T extends DimensionLike>(
  dimensions: DimensionEntry[],
  items: T[],
): { groups: { dimension: DimensionEntry; items: T[] }[]; rest: T[] } {
  const groups = dimensions.map((dimension) => ({
    dimension,
    items: itemsForDimension(items, dimension.id),
  }))
  const grouped = new Set(groups.flatMap((group) => group.items))
  const rest = items.filter((item) => !grouped.has(item))
  return { groups, rest }
}
