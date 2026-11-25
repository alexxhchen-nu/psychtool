import { describe, expect, test } from 'bun:test'
import {
  buildGroups,
  canConfirm,
  canReject,
  dimensionChipLabel,
  dimensionSourceLabel,
  NO_DIMENSION_LABEL,
  NOT_DX_TEXT,
  NOT_MAPPED_GROUP,
  reviewSummaryLine,
} from '../src/dimensions'
import type { DimensionEntry, EvidenceItem } from '../src/types'

// Chip cases from the prototype (data-testid `dimension-chip`):
// `No dimension` | `Dimension · Needs review` | `{name} · Needs review` |
// `{name} · Confirmed by you` | `{name}`.

function item(partial: Partial<EvidenceItem>): EvidenceItem {
  return {
    id: 'ev_1',
    quote: 'q',
    material_id: 'm',
    material_title: 't',
    material_version: 1,
    passage_id: 'p',
    paragraph: 1,
    start: 0,
    end: 1,
    category: 'other',
    category_label: 'Other',
    category_reason: 'r',
    category_set_by: 'suggestion',
    role: 'client',
    role_label: 'Client',
    role_reason: 'r',
    role_set_by: 'suggestion',
    kept_because_corrected: false,
    dimension_id: null,
    dimension_name: null,
    dim_state: 'none',
    dim_reason: '',
    dim_set_by: 'suggestion',
    ...partial,
  }
}

describe('dimensionChipLabel', () => {
  test('rejected item shows "No dimension"', () => {
    expect(
      dimensionChipLabel(item({ dim_state: 'rejected', dim_set_by: 'clinician' })),
    ).toBe(NO_DIMENSION_LABEL)
  })

  test('no dimension with no suggestion shows "No dimension"', () => {
    expect(dimensionChipLabel(item({ dim_state: 'none' }))).toBe(NO_DIMENSION_LABEL)
  })

  test('ambiguous suggestion shows "Dimension · Needs review"', () => {
    expect(
      dimensionChipLabel(item({ dim_state: 'needs_review', dimension_id: null })),
    ).toBe('Dimension · Needs review')
  })

  test('named suggestion shows "{name} · Needs review"', () => {
    expect(
      dimensionChipLabel(
        item({
          dim_state: 'needs_review',
          dimension_id: 'dim_a',
          dimension_name: 'Attention',
        }),
      ),
    ).toBe('Attention · Needs review')
  })

  test('her confirmed choice shows "{name} · Confirmed by you"', () => {
    expect(
      dimensionChipLabel(
        item({
          dim_state: 'confirmed',
          dim_set_by: 'clinician',
          dimension_id: 'dim_a',
          dimension_name: 'Attention',
        }),
      ),
    ).toBe('Attention · Confirmed by you')
  })

  test('system state with a name shows the bare name', () => {
    expect(
      dimensionChipLabel(
        item({ dim_state: 'needs_review', dimension_name: 'Attention', dimension_id: 'dim_a' }),
      ),
    ).toContain('Attention')
  })
})

describe('reviewSummaryLine', () => {
  test('uses the prototype "need review" wording', () => {
    expect(reviewSummaryLine(2, 5)).toBe('2 need review · 5 evidence items')
    expect(reviewSummaryLine(1, 5)).toBe('1 needs review · 5 evidence items')
  })
})

describe('dimensionSourceLabel', () => {
  test('labels the list paragraph', () => {
    expect(dimensionSourceLabel(3)).toBe('Source: your list, paragraph 3')
  })
})

describe('action visibility', () => {
  const mapped = item({ dim_state: 'needs_review', dimension_id: 'dim_a', dimension_name: 'Attention' })
  const confirmed = item({ dim_state: 'confirmed', dim_set_by: 'clinician', dimension_id: 'dim_a', dimension_name: 'Attention' })
  const rejected = item({ dim_state: 'rejected', dim_set_by: 'clinician' })
  const bare = item({ dim_state: 'none' })

  test('confirm and reject only when a dimension exists and is unconfirmed', () => {
    expect(canConfirm(mapped)).toBe(true)
    expect(canReject(mapped)).toBe(true)
    expect(canConfirm(confirmed)).toBe(false)
    expect(canConfirm(bare)).toBe(false)
    expect(canReject(rejected)).toBe(false)
  })
})

describe('buildGroups', () => {
  const dimensions: DimensionEntry[] = [
    { id: 'dim_a', name: 'Attention', passage_id: 'p', paragraph: 1, start: 0, end: 9, quote_text_of_passage_span: 'Attention' },
    { id: 'dim_b', name: 'Sleep', passage_id: 'p', paragraph: 1, start: 11, end: 16, quote_text_of_passage_span: 'Sleep' },
  ]

  test('groups items per dimension and the rest separately', () => {
    const a = item({ id: 'ev_a', dimension_id: 'dim_a', dimension_name: 'Attention', dim_state: 'needs_review' })
    const b = item({ id: 'ev_b', dimension_id: 'dim_b', dimension_name: 'Sleep', dim_state: 'confirmed', dim_set_by: 'clinician' })
    const unsure = item({ id: 'ev_c', dim_state: 'needs_review' })
    const none = item({ id: 'ev_d', dim_state: 'none' })
    const { groups, rest } = buildGroups(dimensions, [a, b, unsure, none])
    expect(groups[0].dimension.id).toBe('dim_a')
    expect(groups[0].items.map((i) => i.id)).toEqual(['ev_a'])
    expect(groups[1].items.map((i) => i.id)).toEqual(['ev_b'])
    expect(rest.map((i) => i.id)).toEqual(['ev_c', 'ev_d'])
  })

  test('rejected items never appear in a dimension group', () => {
    const rejected = item({ id: 'ev_r', dimension_id: 'dim_a', dimension_name: 'Attention', dim_state: 'rejected', dim_set_by: 'clinician' })
    const { groups, rest } = buildGroups(dimensions, [rejected])
    expect(groups[0].items).toEqual([])
    expect(rest.map((i) => i.id)).toEqual(['ev_r'])
  })
})

describe('NOT_DX_TEXT', () => {
  test('is the exact fixed disclaimer', () => {
    expect(NOT_DX_TEXT).toBe('This is not a diagnosis. The diagnosis is yours.')
    expect(NOT_MAPPED_GROUP).toBe('Not mapped or unsure')
  })
})
