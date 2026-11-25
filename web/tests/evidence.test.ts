import { describe, expect, test } from 'bun:test'
import { droppedNotice, evidenceSourceLine, highlightParts } from '../src/evidence'

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
      '1 candidate were dropped because the quote did not match the source exactly.',
    )
  })

  test('uses the plural form for several dropped candidates', () => {
    expect(droppedNotice(3)).toBe(
      '3 candidates were dropped because the quote did not match the source exactly.',
    )
  })
})
