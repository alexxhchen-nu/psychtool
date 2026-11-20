import { ApiError } from './api'
import type { UploadResult } from './types'

export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024
export const UPLOAD_ACCEPT = '.txt,.md,.pdf,.png,.jpg,.jpeg'
const supportedExtensions = new Set(UPLOAD_ACCEPT.split(','))

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
    if (!supportedExtensions.has(extension)) {
      errors.file = 'Choose a .txt, .md, .pdf, .png, .jpg or .jpeg file.'
    } else if (fields.file.size > MAX_UPLOAD_BYTES) {
      errors.file = 'Choose a file no larger than 10 MiB (10,485,760 bytes).'
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
      case 413:
        return 'The file is too large. Choose a file no larger than 10 MiB (10,485,760 bytes).'
      case 415:
        return 'This file type is not supported. Choose a .txt, .md, .pdf, .png, .jpg or .jpeg file.'
      case 503:
        return 'OCR is unavailable on the server; its support may not be installed. Ask an administrator to check OCR, or upload a .txt or .md file.'
    }
  }
  return 'The upload could not be confirmed. Check the material list before trying again.'
}
