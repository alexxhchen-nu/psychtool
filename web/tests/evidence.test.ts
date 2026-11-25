import { describe, expect, test } from 'bun:test'
import {
  CATEGORY_OPTIONS,
  NO_REASON_TEXT,
  ROLE_OPTIONS,
  categoryLabel,
  droppedNotice,
  evidenceSourceLine,
  highlightParts,
  reasonLine,
  roleLabel,
  roleLine,
  setByText,
} from '../src/evidence'
import type { EvidenceCategory, EvidenceRole } from '../src/types'

describe('highlightParts', () => {
  test('slices an ASCII range by code-point offsets', () => {
    const text = 'Mother says he sleeps about 8 hours a night.'
    expect(highlightParts(text, 0, 6)).toEqual({
      before: '',
      mark: 'Mother',
      after: ' says he sleeps about 8 hours a night.',
    })
    expect(highlightParts(text, 7, 31)).toEqual({
      before: 'Mother ',
      mark: 'says he sleeps about 8 h',
      after: 'ours a night.',
    })
  })

  test('keeps CJK offsets aligned with Python code points', () => {
    const text = '他经常熬夜到凌晨。周末会补觉。'
    const start = 0
    const end = '他经常熬夜到凌晨'.length
    expect(highlightParts(text, start, end)).toEqual({
      before: '',
      mark: '他经常熬夜到凌晨',
      after: '。周末会补觉。',
    })
  })

  test('an astral character before the span does not shift offsets', () => {
    const text = '😀 He sleeps about 7 hours.'
    const start = Array.from('😀 ').length // 2 code points
    const mark = 'He sleeps about 7 hours'
    expect(highlightParts(text, start, start + mark.length)).toEqual({
      before: '😀 ',
      mark,
      after: '.',
    })
  })

  test('start/end at the edges of the text', () => {
    const text = 'He walks to school.'
    expect(highlightParts(text, 0, text.length)).toEqual({
      before: '',
      mark: 'He walks to school.',
      after: '',
    })
  })

  test('clamps out-of-range offsets instead of throwing', () => {
    const text = 'short'
    expect(highlightParts(text, 3, 99)).toEqual({ before: 'sho', mark: 'rt', after: '' })
    expect(highlightParts(text, -2, 2)).toEqual({ before: '', mark: 'sh', after: 'ort' })
  })
})

describe('evidenceSourceLine', () => {
  test('formats title, version and paragraph', () => {
    expect(evidenceSourceLine('Caregiver note', 1, 2)).toBe(
      'Caregiver note · version 1 · paragraph 2',
    )
  })
})

describe('droppedNotice', () => {
  test('returns null when nothing was dropped', () => {
    expect(droppedNotice(0)).toBeNull()
  })

  test('uses the singular form for one dropped candidate', () => {
    expect(droppedNotice(1)).toBe(
      '1 candidate was dropped because the quote did not match the source exactly.',
    )
  })

  test('uses the plural form for several dropped candidates', () => {
    expect(droppedNotice(3)).toBe(
      '3 candidates were dropped because the quote did not match the source exactly.',
    )
  })
})

// -- R5 (PT-07 / ADR 0015): category & role labels ----------------------------

describe('categoryLabel', () => {
  test('maps every allowlisted category key to its label', () => {
    expect(categoryLabel('family_history')).toBe('Family history')
    expect(categoryLabel('medical_history')).toBe('Medical history')
    expect(categoryLabel('test_results')).toBe('Test results')
    expect(categoryLabel('behavioral_observations')).toBe('Behavioral observations')
    expect(categoryLabel('development_school')).toBe('Development & school')
    expect(categoryLabel('daily_living')).toBe('Daily living & function')
    expect(categoryLabel('other')).toBe('Other')
    expect(categoryLabel('uncategorized')).toBe('Uncategorized')
  })

  test('passes an unknown key through verbatim', () => {
    expect(categoryLabel('future_key' as EvidenceCategory)).toBe('future_key')
  })
})

describe('roleLabel', () => {
  test('maps every allowlisted role key to its label', () => {
    expect(roleLabel('school')).toBe('School')
    expect(roleLabel('caregiver')).toBe('Caregiver')
    expect(roleLabel('medical_record')).toBe('Medical record')
    expect(roleLabel('clinician')).toBe('Clinician')
    expect(roleLabel('client')).toBe('Client')
    expect(roleLabel('to_confirm')).toBe('To confirm')
  })

  test('passes an unknown key through verbatim', () => {
    expect(roleLabel('future_key' as EvidenceRole)).toBe('future_key')
  })
})

describe('CATEGORY_OPTIONS / ROLE_OPTIONS', () => {
  test('offer exactly the 8 category keys including Other and Uncategorized', () => {
    expect(CATEGORY_OPTIONS.map((option) => option.key)).toEqual([
      'family_history',
      'medical_history',
      'test_results',
      'behavioral_observations',
      'development_school',
      'daily_living',
      'other',
      'uncategorized',
    ])
  })

  test('offer exactly the 6 role keys', () => {
    expect(ROLE_OPTIONS.map((option) => option.key)).toEqual([
      'school',
      'caregiver',
      'medical_record',
      'clinician',
      'client',
      'to_confirm',
    ])
  })
})

describe('roleLine', () => {
  test('formats the source role line', () => {
    expect(roleLine('caregiver')).toBe('From: Caregiver')
    expect(roleLine('to_confirm')).toBe('From: To confirm')
  })
})

describe('reasonLine', () => {
  test('prefixes the reason and keeps the full text', () => {
    expect(reasonLine('The text mentions “mother”, which relates to “Family history”.'))
      .toBe('Why: The text mentions “mother”, which relates to “Family history”.')
  })

  test('falls back to fixed text when the reason is empty', () => {
    expect(reasonLine('')).toBe(`Why: ${NO_REASON_TEXT}`)
  })
})

describe('setByText', () => {
  test('marks her own choices', () => {
    expect(setByText('clinician')).toBe('Set by you')
  })

  test('says nothing for rule suggestions', () => {
    expect(setByText('suggestion')).toBeNull()
  })
})
