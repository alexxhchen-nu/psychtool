import { describe, expect, test } from 'bun:test'
import { isClinicianAuthoredSection } from '../src/sections'

describe('isClinicianAuthoredSection', () => {
  test('is true for diagnostic conclusions and recommendations', () => {
    expect(isClinicianAuthoredSection({ content_types: ['diagnostic_conclusion'] })).toBe(true)
    expect(isClinicianAuthoredSection({ content_types: ['recommendation'] })).toBe(true)
    expect(
      isClinicianAuthoredSection({ content_types: ['source_fact', 'diagnostic_conclusion'] }),
    ).toBe(true)
  })

  test('is false for history, findings and summary', () => {
    expect(isClinicianAuthoredSection({ content_types: ['source_fact'] })).toBe(false)
    expect(
      isClinicianAuthoredSection({ content_types: ['source_fact', 'clinical_interpretation'] }),
    ).toBe(false)
  })

  test('is false for sections with no content types', () => {
    expect(isClinicianAuthoredSection({ content_types: [] })).toBe(false)
  })
})
