// R9-AC3: sections the clinician writes herself. The model must never
// auto-fill them with a diagnosis or recommendation. This mirrors the
// Python helper used by the egress request builder.

import type { TemplateSection } from './types'

export const CLINICIAN_AUTHORED_CONTENT_TYPES = [
  'diagnostic_conclusion',
  'recommendation',
] as const

export function isClinicianAuthoredSection(
  section: Pick<TemplateSection, 'content_types'>,
): boolean {
  return section.content_types.some((type) =>
    (CLINICIAN_AUTHORED_CONTENT_TYPES as readonly string[]).includes(type),
  )
}
