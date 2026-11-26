// PT-12 (GROK-42): sentence-level citation types and the wording filters
// the UI uses before applying or saving a draft. Strings and phrase lists
// must stay in lockstep with psychtool/core/citecheck.py.

import { isClinicianAuthoredSection } from './sections'
import type { DraftSentence, TemplateSection } from './types'

export type { DraftSentence }
export type SentenceState = DraftSentence['state']

export const SUMMARY_DRAFT_REASON =
  'a Summary draft must not contain diagnostic or recommendation wording'

export const DRAFT_FILTER_REASON =
  'draft text must not contain diagnostic wording or un-uploaded manual text'

// Diagnostic phrases from the Python draft filter, minus the dimension
// disclaimer ("this is not a diagnosis"), which is not a violation.
export const DRAFT_DIAGNOSIS_PHRASES = [
  'meets criteria',
  'consistent with a diagnosis of',
  'diagnosis is',
  'suggests a diagnosis',
  'diagnosed with',
  'criteria for',
] as const

// Stem list pending psychologist validation (待验证). See ADR 0021.
export const RECOMMENDATION_STEMS = ['recommend', 'advis', 'suggest', 'refer'] as const
export const RECOMMENDATION_SHOULD_PATTERNS = [
  'should be',
  'should receive',
  'should undergo',
  'should consider',
] as const
export const RECOMMENDATION_PHRASES = RECOMMENDATION_STEMS

const RECOMMENDATION_STEM_RE = new RegExp(
  `\\b(?:${RECOMMENDATION_STEMS.join('|')})\\w*`,
  'i',
)
const RECOMMENDATION_SHOULD_RE = /\bshould\s+(?:be|receive|undergo|consider)\b/i

function recommendationHit(text: string): boolean {
  return RECOMMENDATION_STEM_RE.test(text) || RECOMMENDATION_SHOULD_RE.test(text)
}

const CRITERION_PATTERNS: RegExp[] = [
  /\bcriteri(?:a|on)\s+[A-Za-z]{0,2}\.?\s*\d+\b/i,
  /\b[A-TV-Z]\d{2}\.\d{1,4}\b/,
  /\b\d{3}\.\d{2,4}\b/,
  /\b[A-Z]\.\d{1,2}\b/,
  /\bdsm\b/i,
  /\bicd\b/i,
]

export function isSummarySection(section: Pick<TemplateSection, 'id' | 'title'>): boolean {
  return section.id === 'summary' || section.title.trim().toLowerCase() === 'summary'
}

function containsPhrase(text: string, phrases: readonly string[]): boolean {
  const lowered = text.toLowerCase()
  return phrases.some((phrase) => lowered.includes(phrase))
}

function diagnosticOrManualHit(text: string, uploadedTexts: readonly string[]): boolean {
  if (containsPhrase(text, DRAFT_DIAGNOSIS_PHRASES)) return true
  return CRITERION_PATTERNS.some((pattern) => {
    const match = pattern.exec(text)
    if (match === null) return false
    return !uploadedTexts.some((uploaded) => uploaded.includes(match[0]))
  })
}

export function summaryDraftBlocked(text: string, uploadedTexts: readonly string[] = []): boolean {
  return diagnosticOrManualHit(text, uploadedTexts) || recommendationHit(text)
}

export function draftFilterBlocked(
  section: Pick<TemplateSection, 'id' | 'title' | 'content_types'>,
  text: string,
  uploadedTexts: readonly string[] = [],
): { blocked: boolean; detail: string | null } {
  if (isClinicianAuthoredSection(section)) return { blocked: false, detail: null }
  if (isSummarySection(section)) {
    if (summaryDraftBlocked(text, uploadedTexts)) {
      return { blocked: true, detail: SUMMARY_DRAFT_REASON }
    }
    return { blocked: false, detail: null }
  }
  if (diagnosticOrManualHit(text, uploadedTexts)) {
    return { blocked: true, detail: DRAFT_FILTER_REASON }
  }
  return { blocked: false, detail: null }
}
