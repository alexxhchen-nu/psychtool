import { describe, expect, test } from 'bun:test'
import { validateCaseId, validatePaste } from '../src/case-form'
import type { PasteFields } from '../src/case-form'

function fields(overrides: Partial<PasteFields> = {}): PasteFields {
  return {
    materialId: 'paste-1',
    title: 'Pasted synthetic note',
    provider: 'synthetic author',
    date: '2026-11-20',
    text: 'Synthetic paragraph.',
    syntheticConfirmed: true,
    ...overrides,
  }
}

describe('case id validation', () => {
  test.each(['a', 'case-1', 'Case_2', '0', 'x'.repeat(64)])('accepts %s', (id) => {
    expect(validateCaseId(id)).toBeNull()
  })

  test.each(['', '..', 'a/b', ' spaced', '-lead', '_lead', 'case.1', 'x'.repeat(65)])('rejects %s', (id) => {
    expect(validateCaseId(id)).not.toBeNull()
  })
})

describe('paste validation', () => {
  test('accepts a complete synthetic paste', () => {
    expect(validatePaste(fields())).toEqual({})
  })

  test('requires the synthetic confirmation', () => {
    expect(validatePaste(fields({ syntheticConfirmed: false })).syntheticConfirmed).toBeDefined()
  })

  test('requires non-empty text', () => {
    expect(validatePaste(fields({ text: '   ' })).text).toBeDefined()
  })

  test('rejects a bad material id', () => {
    expect(validatePaste(fields({ materialId: 'bad id!' })).materialId).toBeDefined()
  })

  test('requires title, provider and date', () => {
    const errors = validatePaste(fields({ title: ' ', provider: '', date: '' }))
    expect(errors.title).toBeDefined()
    expect(errors.provider).toBeDefined()
    expect(errors.date).toBeDefined()
  })
})
