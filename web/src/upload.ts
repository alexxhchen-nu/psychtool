import { ApiError } from './api'
import type { UploadResult } from './types'

export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024
// M1 server rules (ADR 0012): text and Markdown only; scans go through no
// OCR on the server, so the picker never offers them.
export const UPLOAD_ACCEPT = '.txt,.md'
const supportedExtensions = new Set(UPLOAD_ACCEPT.split(','))
const scanExtensions = new Set(['.pdf', '.png', '.jpg', '.jpeg'])

export const SCAN_NOT_SUPPORTED_MESSAGE =
  'Scanned PDFs and images are not supported in this version. Upload a .txt or .md file.'
export const UNSUPPORTED_TYPE_MESSAGE = 'Only .txt and .md files are supported. Upload a .txt or .md file.'
export const TOO_LARGE_MESSAGE = 'The file is too large. The limit is 10 MiB (10,485,760 bytes).'

export interface MaterialUploadFields {
  file: Pick<File, 'name' | 'size'> | null
  materialId: string
  title: string
  provider: string
  date: string
}
export type UploadFieldErrors = Partial<Record<keyof MaterialUploadFields, string>>

export function validateMaterialUpload(fields: MaterialUploadFields): UploadFieldErrors {
  const errors: UploadFieldErrors = {}
  if (!fields.file) {
    errors.file = 'Choose a file to upload.'
  } else {
    const dot = fields.file.name.lastIndexOf('.')
    const extension = dot > 0 ? fields.file.name.slice(dot).toLowerCase() : ''
    if (scanExtensions.has(extension)) {
      errors.file = SCAN_NOT_SUPPORTED_MESSAGE
    } else if (!supportedExtensions.has(extension)) {
      errors.file = UNSUPPORTED_TYPE_MESSAGE
    } else if (fields.file.size > MAX_UPLOAD_BYTES) {
      errors.file = TOO_LARGE_MESSAGE
    }
  }
  if (fields.materialId.length < 1 || fields.materialId.length > 64 || /[^A-Za-z0-9_-]/.test(fields.materialId)) {
    errors.materialId = 'Use 1–64 ASCII letters, digits, underscores or hyphens for the anonymous material ID.'
  }
  if (!fields.title.trim()) errors.title = 'Enter a title.'
  if (!fields.provider.trim()) errors.provider = 'Enter a provider.'
  if (!fields.date.trim()) errors.date = 'Choose a date.'
  return errors
}

export interface UploadSummary {
  materialId: string
  version: number
  passageCount: number
  identifierCategories: string[]
}

export function summarizeUpload(result: UploadResult): UploadSummary {
  return {
    materialId: result.material.id,
    version: result.material.version,
    passageCount: result.material.passages.length,
    identifierCategories: [...new Set(result.identifier_findings.map((finding) => finding.category))],
  }
}

export function uploadErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    // The server's fixed rejection message is safe to show verbatim: it is a
    // constant chosen from a small allowlist and never quotes user input.
    if (error.serverMessage) return error.serverMessage
    switch (error.status) {
      case 0:
        return 'The upload could not be confirmed. The server may have received the file; check the material list before trying again.'
      case 400:
      case 422:
        return 'The server could not accept this file or its details. Check the file and required fields, then try again.'
      case 403:
        return 'The server did not allow this upload. Ask an administrator to check access.'
      case 404:
        return 'The workspace could not be found. Reopen the workspace before uploading.'
      case 409:
        return 'Confirm that this case uses only synthetic or separately approved materials before uploading.'
      case 413:
        return TOO_LARGE_MESSAGE
      case 415:
        return UNSUPPORTED_TYPE_MESSAGE
      case 503:
        return 'The upload service is unavailable. Ask an administrator to check the server, or try again later.'
    }
  }
  return 'The upload could not be confirmed. Check the material list before trying again.'
}
