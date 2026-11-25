import { describe, expect, test } from 'bun:test'
import { ApiError } from '../src/api'
import type { UploadResult } from '../src/types'
import {
  heldBackNotice,
  SCAN_NOT_SUPPORTED_MESSAGE,
  summarizeUpload,
  TOO_LARGE_MESSAGE,
  UNSUPPORTED_TYPE_MESSAGE,
  uploadErrorMessage,
  validateMaterialUpload,
} from '../src/upload'
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
  test.each(['notes.txt', 'notes.md', 'NOTES.MD', '.notes.MD'])(
    'accepts the supported final extension in %s',
    (name) => {
      expect(validateMaterialUpload(fields({ file: { name, size: 42 } }))).toEqual({})
    },
  )

  // R12 (M1): scans and images get the fixed plain explanation.
  test.each(['scan.pdf', 'scan.png', 'scan.jpg', 'scan.jpeg', 'SCAN.PDF'])(
    'rejects scans and images with the R12 explanation: %s',
    (name) => {
      expect(validateMaterialUpload(fields({ file: { name, size: 42 } })).file).toBe(SCAN_NOT_SUPPORTED_MESSAGE)
    },
  )

  test.each(['notes', '.txt', 'notes.exe', 'notes.txt.exe', 'notes.gif', 'notes.webp', 'notes.docx', 'notes.txt ', 'notes.'])(
    'rejects unsupported or missing extensions with the type message: %s',
    (name) => {
      expect(validateMaterialUpload(fields({ file: { name, size: 42 } })).file).toBe(UNSUPPORTED_TYPE_MESSAGE)
    },
  )

  test('requires a selected file', () => {
    expect(validateMaterialUpload(fields({ file: null })).file).toBeDefined()
  })

  test.each([0, 10_485_759, 10_485_760])('accepts a supported file of %d bytes', (size) => {
    expect(validateMaterialUpload(fields({ file: { name: 'notes.txt', size } }))).toEqual({})
  })

  test('rejects the first byte above ten MiB with the size message', () => {
    expect(validateMaterialUpload(fields({ file: { name: 'notes.txt', size: 10_485_761 } })).file).toBe(TOO_LARGE_MESSAGE)
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

  test.each([0, 400, 403, 404, 409, 413, 415, 422, 500, 503])('does not expose the API error message for status %d', (status) => {
    const error = new ApiError(status)
    error.message = 'PRIVATE_SERVER_DETAIL'
    const message = uploadErrorMessage(error)
    expect(message).not.toContain('PRIVATE_SERVER_DETAIL')
  })

  test('shows the fixed server rejection message when one was sent', () => {
    // Only the upload endpoint's allowlisted {detail, reason} body reaches
    // serverMessage; it is a server-side constant, never user input.
    const error = new ApiError(400, SCAN_NOT_SUPPORTED_MESSAGE)
    expect(uploadErrorMessage(error)).toBe(SCAN_NOT_SUPPORTED_MESSAGE)
  })

  test('does not expose arbitrary thrown values', () => {
    for (const error of [new Error('PRIVATE_EXCEPTION'), 'PRIVATE_EXCEPTION', { status: 503, detail: 'PRIVATE_EXCEPTION' }, null]) {
      expect(uploadErrorMessage(error)).not.toContain('PRIVATE_EXCEPTION')
    }
  })
})

describe('R13 held-back notice', () => {
  test('is null when nothing was held back', () => {
    expect(heldBackNotice(0)).toBeNull()
    expect(heldBackNotice(undefined)).toBeNull()
    expect(heldBackNotice(null)).toBeNull()
    expect(heldBackNotice(-2)).toBeNull()
  })

  test('uses the singular form for exactly one paragraph', () => {
    const notice = heldBackNotice(1)
    expect(notice).not.toBeNull()
    expect(notice).toContain('1 paragraph held back: it appears to contain test items, norms or scoring rules.')
    expect(notice).toContain('It was not added to this case')
    expect(notice).not.toContain('paragraphs')
  })

  test('uses the plural form for three paragraphs', () => {
    const notice = heldBackNotice(3)
    expect(notice).not.toBeNull()
    expect(notice).toContain('3 paragraphs held back: they appear to contain test items, norms or scoring rules.')
    expect(notice).toContain('They were not added to this case')
  })

  test('never includes a filename or any upload text', () => {
    for (const count of [1, 2, 5]) {
      const notice = heldBackNotice(count)!
      expect(notice).not.toMatch(/\.txt|\.md|notes|file/i)
    }
  })
})

describe('R13 protected-content error reasons', () => {
  // Both {detail, reason} bodies from the server carry only fixed text, so
  // the detail is shown verbatim, exactly like the scan rejection.
  test('shows the fixed detail for protected_content', () => {
    const detail = 'Paragraphs were held back: they appear to contain test items, norms or scoring rules.'
    const error = new ApiError(400, detail)
    expect(uploadErrorMessage(error)).toBe(detail)
  })

  test('shows the fixed detail for protected_check_failed', () => {
    const detail = 'The upload could not be checked for protected test content, so it was rejected. Nothing was stored.'
    const error = new ApiError(503, detail)
    expect(uploadErrorMessage(error)).toBe(detail)
  })
})
