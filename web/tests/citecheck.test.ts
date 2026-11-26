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
    expect(summaryDraftBlocked('The notes advised a follow-up meeting.')).toBe(true)
    expect(summaryDraftBlocked('The student should receive extra time.')).toBe(true)
    expect(summaryDraftBlocked('The student should undergo a hearing screen.')).toBe(true)
    expect(summaryDraftBlocked('The team should consider a later start time.')).toBe(true)
    expect(summaryDraftBlocked('Scores sit below the mid range on working memory.')).toBe(false)
  })

  test('blocks treatment plan', () => {
    expect(summaryDraftBlocked('A treatment plan is already on file from last year.')).toBe(true)
  })

  test('blocks refer to', () => {
    expect(summaryDraftBlocked('The team will refer to a community tutor.')).toBe(true)
  })

  test('blocks refer her to', () => {
    expect(summaryDraftBlocked('I will refer her to a community tutor.')).toBe(true)
  })

  test('blocks refer him to', () => {
    expect(summaryDraftBlocked('I will refer him to a community tutor.')).toBe(true)
  })

  test('blocks refer them to', () => {
    expect(summaryDraftBlocked('I will refer them to a community tutor.')).toBe(true)
  })

  test('blocks refer the family to', () => {
    expect(summaryDraftBlocked('The team will refer the family to a community tutor.')).toBe(true)
  })

  test('blocks refer for', () => {
    expect(summaryDraftBlocked('The team will refer for a community tutor evaluation.')).toBe(true)
  })

  test('blocks referral to', () => {
    expect(summaryDraftBlocked('A referral to a community tutor is already in the file.')).toBe(true)
  })

  test('blocks referral for', () => {
    expect(summaryDraftBlocked('A referral for a community tutor is already in the file.')).toBe(true)
  })

  test('blocks should be referred', () => {
    expect(summaryDraftBlocked('The student should be referred to a community tutor.')).toBe(true)
  })

  test('blocks referred to', () => {
    expect(summaryDraftBlocked('The student was referred to a community tutor.')).toBe(true)
  })

  test('blocks referred for', () => {
    expect(summaryDraftBlocked('The student was referred for a hearing screen.')).toBe(true)
  })

  test('allows for reference', () => {
    expect(summaryDraftBlocked('For reference, the session started at 9.')).toBe(false)
  })

  test('allows the reference group', () => {
    expect(summaryDraftBlocked('The reference group scored in the mid range.')).toBe(false)
  })

  test('allows referred by her school', () => {
    expect(summaryDraftBlocked('She was referred by her school for this evaluation.')).toBe(false)
  })

  // Left unchanged in PT-23; still blocked and still 待验证. See ADR 0021.
  test('still flags the results suggest', () => {
    expect(summaryDraftBlocked('The results suggest a slower processing speed on this task.')).toBe(true)
  })

  test('still flags should be noted', () => {
    expect(summaryDraftBlocked('It should be noted that the session ran past the scheduled time.')).toBe(true)
  })

  test('still flags advisory', () => {
    expect(summaryDraftBlocked('The advisory committee met last week.')).toBe(true)
  })

  test('still flags suggestion', () => {
    expect(summaryDraftBlocked('A suggestion in the file is to repeat the timed task.')).toBe(true)
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
