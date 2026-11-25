/** Pure helpers for the create-case and paste-text flows (unit-tested with bun). */

export const CASE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/
export const MATERIAL_ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/

export interface PasteFields {
  materialId: string
  title: string
  provider: string
  date: string
  text: string
  syntheticConfirmed: boolean
}

export type PasteFieldErrors = Partial<Record<keyof PasteFields, string>>

export function validateCaseId(caseId: string): string | null {
  if (!CASE_ID_PATTERN.test(caseId)) {
    return 'Use 1–64 characters: letters, digits, underscores or hyphens, starting with a letter or digit.'
  }
  return null
}

export function validatePaste(fields: PasteFields): PasteFieldErrors {
  const errors: PasteFieldErrors = {}
  if (!MATERIAL_ID_PATTERN.test(fields.materialId)) {
    errors.materialId = 'Use 1–64 ASCII letters, digits, underscores or hyphens for the anonymous material ID.'
  }
  if (!fields.title.trim()) errors.title = 'Enter a title.'
  if (!fields.provider.trim()) errors.provider = 'Enter a provider.'
  if (!fields.date.trim()) errors.date = 'Choose a date.'
  if (!fields.text.trim()) errors.text = 'Paste the synthetic text.'
  if (!fields.syntheticConfirmed) {
    errors.syntheticConfirmed = 'Confirm the text is synthetic before pasting.'
  }
  return errors
}
