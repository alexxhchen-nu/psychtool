import { describe, expect, test } from 'bun:test'
import {
  CLINICIAN_AUTHORED_NOTICE,
  applyGeneratedText,
  canApplyGeneratedText,
  markSentenceJudgment,
  canApproveSection,
  draftFromSectionState,
  editDraftText,
  egressPrimaryStepActive,
  saveBarPrimaryAction,
  saveStateLabel,
  sectionUsesGeneration,
  toggleDraftClaim,
} from '../src/section-editor'
import type { TemplateSection } from '../src/types'

function section(id: string, contentTypes: string[], gate: TemplateSection['review_gate'] = 'standard'): TemplateSection {
  return {
    id,
    title: id,
    required: true,
    review_gate: gate,
    content_types: contentTypes,
    allowed_sources: [],
  }
}

const HISTORY = section('history', ['source_fact'])
const FINDINGS = section('findings', ['source_fact', 'clinical_interpretation'], 'licensed_clinician')
const IMPRESSIONS = section('clinical_impressions', ['diagnostic_conclusion'], 'licensed_clinician')
const RECOMMENDATIONS = section('recommendations', ['recommendation'], 'licensed_clinician')

const DRAFT = draftFromSectionState({
  text: '',
  status: 'empty',
  reviewer: null,
  claim_ids: [],
})

describe('clinician-authored sections', () => {
  test('do not use prepare/approve/send', () => {
    expect(sectionUsesGeneration(HISTORY)).toBe(true)
    expect(sectionUsesGeneration(FINDINGS)).toBe(true)
    expect(sectionUsesGeneration(IMPRESSIONS)).toBe(false)
    expect(sectionUsesGeneration(RECOMMENDATIONS)).toBe(false)
  })

  test('never receive generated text or generated claim selections', () => {
    for (const target of [IMPRESSIONS, RECOMMENDATIONS]) {
      const next = applyGeneratedText(target, DRAFT, 'FAKE MODEL DIAGNOSIS', ['claim-1'])
      expect(next).toEqual(DRAFT)
      expect(next.text).toBe('')
    }
  })

  test('the notice names both impressions and recommendations and says never sent', () => {
    expect(CLINICIAN_AUTHORED_NOTICE).toContain('Clinical impressions')
    expect(CLINICIAN_AUTHORED_NOTICE).toContain('recommendations')
    expect(CLINICIAN_AUTHORED_NOTICE).toContain('never sent to the AI assistant')
  })

  test('she can still attach evidence prompts without gaining body text', () => {
    const attached = toggleDraftClaim(DRAFT, 'claim-1')
    expect(attached.claimIds).toEqual(['claim-1'])
    expect(attached.text).toBe('')
  })
})

describe('ordinary sections', () => {
  test('generated text lands unsaved as a draft, keeping request claims', () => {
    const next = applyGeneratedText(HISTORY, DRAFT, 'FAKE OFFLINE RESPONSE', ['claim-1'])
    expect(next.text).toBe('FAKE OFFLINE RESPONSE')
    expect(next.claimIds).toEqual(['claim-1'])
    expect(next.status).toBe('draft')
  })

  test('editing an approved section falls back to draft', () => {
    const approved = { ...DRAFT, status: 'approved' as const, text: 'old' }
    expect(editDraftText(approved, 'new').status).toBe('draft')
  })
})

describe('save state messaging', () => {
  test('shows Unsaved changes while dirty and Saved otherwise', () => {
    expect(saveStateLabel(true)).toBe('Unsaved changes')
    expect(saveStateLabel(false)).toBe('Saved')
  })
})

describe('one primary button (save bar)', () => {
  const ready = { text: 'Saved words', status: 'draft' as const, reviewer: '', claimIds: [] }
  const licensed = { ...ready, reviewer: 'Dr Chen' }

  test('Approve section can run only when saved, non-empty, and not already approved', () => {
    expect(canApproveSection(ready, 'standard')).toBe(true)
    expect(canApproveSection({ ...ready, status: 'approved' }, 'standard')).toBe(false)
    expect(canApproveSection({ ...ready, text: '  ' }, 'standard')).toBe(false)
    expect(canApproveSection({ ...ready, reviewer: '' }, 'licensed_clinician')).toBe(false)
    expect(canApproveSection(licensed, 'licensed_clinician')).toBe(true)
  })

  test('save bar primary is Approve when it can run, else Save when dirty, else none', () => {
    expect(saveBarPrimaryAction({ dirty: false, canApprove: true, sendStepActive: false })).toBe('approve')
    expect(saveBarPrimaryAction({ dirty: true, canApprove: true, sendStepActive: false })).toBe('save')
    expect(saveBarPrimaryAction({ dirty: true, canApprove: false, sendStepActive: false })).toBe('save')
    expect(saveBarPrimaryAction({ dirty: false, canApprove: false, sendStepActive: false })).toBe(null)
  })

  test('a live send-pane step takes the view primary; the save bar has none', () => {
    expect(saveBarPrimaryAction({ dirty: true, canApprove: false, sendStepActive: true })).toBe(null)
    expect(saveBarPrimaryAction({ dirty: false, canApprove: true, sendStepActive: true })).toBe(null)
  })

  test('egress primary is the ready Approve request or Send once step', () => {
    expect(egressPrimaryStepActive('idle', false, false)).toBe(false)
    expect(egressPrimaryStepActive('prepared', false, false)).toBe(false)
    expect(egressPrimaryStepActive('prepared', true, false)).toBe(true)
    expect(egressPrimaryStepActive('prepared', true, true)).toBe(false)
    expect(egressPrimaryStepActive('approving', true, true)).toBe(true)
    expect(egressPrimaryStepActive('approved', false, false)).toBe(true)
    expect(egressPrimaryStepActive('sending', false, true)).toBe(true)
    expect(egressPrimaryStepActive('sent', false, false)).toBe(false)
  })
})


const SUMMARY = section('summary', ['source_fact', 'clinical_interpretation'], 'licensed_clinician')

describe('canApplyGeneratedText', () => {
  test('is false for clinician-authored sections', () => {
    expect(canApplyGeneratedText(IMPRESSIONS, 'any text')).toBe(false)
    expect(canApplyGeneratedText(RECOMMENDATIONS, 'I recommend tutoring.')).toBe(false)
  })

  test('is false for a blocked Summary or History draft', () => {
    expect(canApplyGeneratedText(SUMMARY, 'I recommend weekly tutoring.')).toBe(false)
    expect(canApplyGeneratedText(HISTORY, 'This is consistent with a diagnosis of delay.')).toBe(false)
  })

  test('is true for a clean History or Summary draft', () => {
    expect(canApplyGeneratedText(HISTORY, 'The teacher notes late-task looking away.')).toBe(true)
    expect(canApplyGeneratedText(SUMMARY, 'Working memory scores sit below the mid range.')).toBe(true)
  })
})


describe('markSentenceJudgment', () => {
  const unsourced = {
    sentence_id: 'sent_1',
    ordinal: 1,
    text: 'The client is very popular with peers.',
    evidence_ids: [] as string[],
    state: 'unverified' as const,
  }
  const draft = { ...DRAFT, text: unsourced.text, sentences: [unsourced], status: 'draft' as const }

  test('marks an unsourced sentence as my judgment and can unmark it back to unverified', () => {
    const judged = markSentenceJudgment(draft, 'sent_1', true)
    expect(judged.sentences[0].state).toBe('my_judgment')
    const unmarked = markSentenceJudgment(judged, 'sent_1', false)
    expect(unmarked.sentences[0].state).toBe('unverified')
  })
})
