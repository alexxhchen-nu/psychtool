import { describe, expect, test } from 'bun:test'
import { ApiError } from '../src/api'
import type { UploadResult } from '../src/types'
import { summarizeUpload, uploadErrorMessage, validateMaterialUpload } from '../src/upload'
import type { MaterialUploadFields } from '../src/upload'

function fields(overrides: Partial<MaterialUploadFields> = {}): MaterialUploadFields {
  return {
    file: { name: 'notes.txt', size: 42 },
    materialId: 'intake_01-a',
    title: 'Synthetic intake',
    provider: 'Self report',
    date: '2026-11-09',
    ...overrides,
  }
}

describe('material upload validation', () => {
  test.each(['notes.txt', 'notes.md', 'notes.pdf', 'notes.png', 'notes.jpg', 'notes.jpeg', 'NOTES.PDF', '.notes.MD'])(
    'accepts the supported final extension in %s',
    (name) => {
      expect(validateMaterialUpload(fields({ file: { name, size: 42 } }))).toEqual({})
    },
  )

  test.each(['notes', '.txt', 'notes.exe', 'notes.txt.exe', 'notes.gif', 'notes.webp', 'notes.pdf ', 'notes.'])(
    'rejects unsupported or missing extensions in %s',
    (name) => {
      expect(validateMaterialUpload(fields({ file: { name, size: 42 } })).file).toBeDefined()
    },
  )

  test('requires a selected file', () => {
    expect(validateMaterialUpload(fields({ file: null })).file).toBeDefined()
  })

  test.each([0, 10_485_759, 10_485_760])('accepts a supported file of %d bytes', (size) => {
    expect(validateMaterialUpload(fields({ file: { name: 'notes.txt', size } }))).toEqual({})
  })

  test('rejects the first byte above ten MiB', () => {
    expect(validateMaterialUpload(fields({ file: { name: 'notes.txt', size: 10_485_761 } })).file).toBeDefined()
  })

  test.each(['a', 'Z', '0', '_', '-', 'Aa09_-', 'a'.repeat(64)])('accepts an ASCII slug at valid boundaries: %s', (materialId) => {
    expect(validateMaterialUpload(fields({ materialId }))).toEqual({})
  })

  test.each(['', 'a'.repeat(65), 'case name', ' case', 'case ', 'case\n', 'case\r\n', '../case', 'case/name', 'case\\name', 'case.name', 'café', '个案', 'case\u0000'])(
    'rejects invalid slugs without normalizing them: %j',
    (materialId) => {
      expect(validateMaterialUpload(fields({ materialId })).materialId).toBeDefined()
    },
  )

  test.each(['title', 'provider', 'date'] as const)('requires a nonblank %s', (field) => {
    expect(validateMaterialUpload(fields({ [field]: '' }))[field]).toBeDefined()
    expect(validateMaterialUpload(fields({ [field]: ' \t\n ' }))[field]).toBeDefined()
  })

  test('reports every invalid field without changing the entered values', () => {
    const input = fields({ file: null, materialId: 'case name', title: ' ', provider: '', date: '' })
    const original = { ...input }
    expect(Object.keys(validateMaterialUpload(input)).sort()).toEqual(['date', 'file', 'materialId', 'provider', 'title'])
    expect(input).toEqual(original)
  })
})

describe('privacy-safe upload presentation', () => {
  test('projects only identity, version, passage count and unique category names', () => {
    const result: UploadResult = {
      material: {
        id: 'intake-1', case_id: 'case-1', title: 'PRIVATE_TITLE', provider: 'PRIVATE_PROVIDER', date: 'PRIVATE_DATE', version: 2,
        passages: [{ id: 'p1', text: 'PRIVATE_SOURCE_TEXT' }, { id: 'p2', text: 'PRIVATE_SOURCE_TEXT' }],
      },
      identifier_findings: [
        { category: 'telephone', label: 'PRIVATE_FINDING_LABEL' },
        { category: 'name', label: 'PRIVATE_FINDING_LABEL' },
        { category: 'telephone', label: 'PRIVATE_FINDING_LABEL' },
      ],
      requires_human_review: true,
    }
    expect(summarizeUpload(result)).toEqual({
      materialId: 'intake-1', version: 2, passageCount: 2, identifierCategories: ['telephone', 'name'],
    })
  })

  test.each([0, 400, 403, 404, 413, 415, 422, 500, 503])('does not expose the API error message for status %d', (status) => {
    const error = new ApiError(status)
    error.message = 'PRIVATE_SERVER_DETAIL'
    const message = uploadErrorMessage(error)
    expect(message).not.toContain('PRIVATE_SERVER_DETAIL')
  })


  test('does not expose arbitrary thrown values', () => {
    for (const error of [new Error('PRIVATE_EXCEPTION'), 'PRIVATE_EXCEPTION', { status: 503, detail: 'PRIVATE_EXCEPTION' }, null]) {
      expect(uploadErrorMessage(error)).not.toContain('PRIVATE_EXCEPTION')
    }
  })
})
