import { describe, expect, test } from 'bun:test'
import {
  DRAFT_FILTER_REASON,
  SUMMARY_DRAFT_REASON,
  draftFilterBlocked,
  isSummarySection,
  summaryDraftBlocked,
} from '../src/citecheck'
import type { TemplateSection } from '../src/types'

function section(id: string, contentTypes: string[]): TemplateSection {
  return {
    id,
    title: id,
    required: true,
    review_gate: 'standard',
    content_types: contentTypes,
    allowed_sources: [],
  }
}

const HISTORY = section('history', ['source_fact'])
const SUMMARY = section('summary', ['source_fact', 'clinical_interpretation'])
const FINDINGS = section('findings', ['source_fact', 'clinical_interpretation'])
const IMPRESSIONS = section('clinical_impressions', ['diagnostic_conclusion'])

describe('isSummarySection', () => {
  test('matches the summary id or title only', () => {
    expect(isSummarySection(SUMMARY)).toBe(true)
    expect(isSummarySection(HISTORY)).toBe(false)
    expect(isSummarySection(FINDINGS)).toBe(false)
    expect(isSummarySection({ ...HISTORY, id: 'other', title: 'Summary' })).toBe(true)
  })
})

describe('summaryDraftBlocked', () => {
  test('flags diagnostic and recommendation wording', () => {
    expect(summaryDraftBlocked('The profile suggests a diagnosis of a delay.')).toBe(true)
    expect(summaryDraftBlocked('I recommend weekly tutoring.')).toBe(true)
    expect(summaryDraftBlocked('Scores sit below the mid range on working memory.')).toBe(false)
  })
})

describe('draftFilterBlocked', () => {
  test('refuses a Summary with diagnostic or recommendation wording', () => {
    expect(draftFilterBlocked(SUMMARY, 'I recommend weekly tutoring.')).toEqual({
      blocked: true,
      detail: SUMMARY_DRAFT_REASON,
    })
    expect(draftFilterBlocked(SUMMARY, 'This suggests a diagnosis of delay.')).toEqual({
      blocked: true,
      detail: SUMMARY_DRAFT_REASON,
    })
  })

  test('refuses History with diagnostic wording or un-uploaded criterion text', () => {
    expect(draftFilterBlocked(HISTORY, 'This is consistent with a diagnosis of inattention.')).toEqual({
      blocked: true,
      detail: DRAFT_FILTER_REASON,
    })
    expect(draftFilterBlocked(HISTORY, 'The notes mention Criterion A1.')).toEqual({
      blocked: true,
      detail: DRAFT_FILTER_REASON,
    })
    expect(draftFilterBlocked(
      HISTORY,
      'The notes mention Criterion A1.',
      ['The list includes Criterion A1 as a heading.'],
    )).toEqual({ blocked: false, detail: null })
  })

  test('does not filter clinician-authored sections', () => {
    expect(draftFilterBlocked(
      IMPRESSIONS,
      'My impression is consistent with a diagnosis of a reading difficulty.',
    )).toEqual({ blocked: false, detail: null })
  })

  test('the disclaimer phrase is not a violation', () => {
    const text = 'Scores are below mid range. This is not a diagnosis, only a summary of testing.'
    expect(draftFilterBlocked(HISTORY, text)).toEqual({ blocked: false, detail: null })
    expect(draftFilterBlocked(SUMMARY, text)).toEqual({ blocked: false, detail: null })
  })
})
