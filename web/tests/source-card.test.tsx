import { describe, expect, test } from 'bun:test'
import { isValidElement, type ReactElement, type ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ClaimRow from '../src/components/ClaimRow'
import EvidenceRow from '../src/components/EvidenceRow'
import ReportColumns from '../src/components/ReportColumns'
import SourceCard from '../src/components/SourceCard'
import {
  claimConfirmation,
  evidenceConfirmation,
  sourceCardFromClaim,
  sourceCardFromEvidence,
  SOURCE_LOCATION_NOTE,
  sourceLocationLine,
} from '../src/source-card'
import type { Claim, EvidenceItem, Material } from '../src/types'

function item(partial: Partial<EvidenceItem> = {}): EvidenceItem {
  return {
    id: 'ev_1',
    quote: 'She reads slowly in class.',
    material_id: 'mat_1',
    material_title: 'Teacher note',
    material_version: 2,
    passage_id: 'p1',
    paragraph: 3,
    start: 12,
    end: 40,
    category: 'development_school',
    category_label: 'Development & school',
    category_reason: 'r',
    category_set_by: 'suggestion',
    role: 'school',
    role_label: 'School',
    role_reason: 'r',
    role_set_by: 'suggestion',
    kept_because_corrected: false,
    dimension_id: null,
    dimension_name: null,
    dim_state: 'needs_review',
    dim_reason: '',
    dim_set_by: 'suggestion',
    ...partial,
  }
}

function claim(partial: Partial<Claim> = {}): Claim {
  return {
    id: 'c1',
    case_id: 'case-1',
    version: 1,
    text: 'She reads slowly in class.',
    category: 'source_statement',
    topic: 'school',
    verification_status: 'pending',
    provider_role: 'other_report',
    source_document_id: 'mat_1',
    source_version: 2,
    source_passage_id: 'p1',
    evidence_ids: ['ev_1'],
    ...partial,
  }
}

function material(partial: Partial<Material> = {}): Material {
  return {
    id: 'mat_1',
    case_id: 'case-1',
    title: 'Teacher note',
    provider: 'school',
    date: '2026-01-01',
    version: 2,
    passages: [{ id: 'p1', text: 'She reads slowly in class.' }],
    ...partial,
  }
}

function walk(node: ReactNode, visit: (el: ReactElement) => void): void {
  if (node == null || typeof node === 'boolean') return
  if (Array.isArray(node)) {
    for (const child of node) walk(child, visit)
    return
  }
  if (!isValidElement(node)) return
  if (typeof node.type === 'function') {
    const rendered = (node.type as (props: object) => ReactNode)(node.props as object)
    walk(rendered, visit)
    return
  }
  visit(node)
  walk((node.props as { children?: ReactNode }).children, visit)
}

function clickTestId(tree: ReactNode, testId: string): void {
  let clicked = false
  walk(tree, (el) => {
    const props = el.props as { 'data-testid'?: string; onClick?: () => void }
    if (props['data-testid'] === testId && props.onClick) {
      props.onClick()
      clicked = true
    }
  })
  if (!clicked) throw new Error(`no clickable node with data-testid=${testId}`)
}

describe('source card location (R8-AC2)', () => {
  test('renders only locations that exist, with 1-based inclusive characters', () => {
    const card = sourceCardFromEvidence(item())
    expect(sourceLocationLine(card)).toBe(
      'Teacher note · version 2 · paragraph 3 · characters 13–40',
    )
  })

  test('omits a missing character range and never invents a page', () => {
    const card = sourceCardFromEvidence(item({ start: undefined, end: undefined }))
    // EvidenceItem fields are numbers, so simulate a card with no range:
    const withoutRange = { ...card, start: null, end: null, paragraph: null }
    const line = sourceLocationLine(withoutRange)
    expect(line).toBe('Teacher note · version 2')
    expect(line).not.toMatch(/page/i)
    expect(line).not.toMatch(/characters/i)
    expect(line).not.toMatch(/paragraph/i)
  })

  test('fails if a nonexistent page (e.g. page 12) is rendered', () => {
    const card = sourceCardFromEvidence(item())
    const html = renderToStaticMarkup(<SourceCard card={card} onClose={() => undefined} />)
    expect(sourceLocationLine(card)).not.toMatch(/page\s*12/i)
    expect(html).not.toMatch(/page\s*12/i)
    expect(html).not.toMatch(/page\s*\d+/i)
    expect(html).toContain('Teacher note · version 2 · paragraph 3 · characters 13–40')
    expect(html).toContain(SOURCE_LOCATION_NOTE)
  })

  test('a claim card uses the passage text and omits unknown paragraph or characters', () => {
    const card = sourceCardFromClaim(claim(), [material()])
    expect(card.quote).toBe('She reads slowly in class.')
    expect(card.materialTitle).toBe('Teacher note')
    expect(card.materialVersion).toBe(2)
    expect(card.providerRole).toBe('Other report')
    expect(sourceLocationLine(card)).toBe('Teacher note · version 2')
    expect(sourceLocationLine(card)).not.toMatch(/page/i)
  })
})

describe('confirmation tags', () => {
  test('maps evidence and claim confirmation to the prototype shapes', () => {
    expect(evidenceConfirmation(item({ dim_state: 'confirmed' }))).toBe('verified')
    expect(evidenceConfirmation(item({ dim_state: 'rejected' }))).toBe('unverified')
    expect(evidenceConfirmation(item({ dim_state: 'needs_review' }))).toBe('needs_review')
    expect(evidenceConfirmation(item({
      category_set_by: 'clinician',
      role_set_by: 'clinician',
      dim_state: 'none',
    }))).toBe('verified')
    expect(claimConfirmation(claim({ verification_status: 'verified' }))).toBe('verified')
    expect(claimConfirmation(claim({ verification_status: 'pending' }))).toBe('needs_review')
    expect(claimConfirmation(claim({ verification_status: 'conflict-viewed' }))).toBe('unverified')
  })
})

describe('click-to-source does not use a modal (R8-AC1)', () => {
  test('the source card and the editor sit side by side in the three-column grid', () => {
    const card = sourceCardFromEvidence(item())
    const html = renderToStaticMarkup(
      <ReportColumns
        rail={<nav>Report sections</nav>}
        editor={<div data-testid="section-editor">Draft stays visible</div>}
        source={<SourceCard card={card} onClose={() => undefined} />}
      />,
    )
    expect(html).toContain('class="report-grid"')
    expect(html).toContain('data-testid="section-editor"')
    expect(html).toContain('Draft stays visible')
    expect(html).toContain('data-testid="source-card"')
    expect(html).toContain('She reads slowly in class.')
    expect(html).toContain('School')
    expect(html).not.toContain('role="dialog"')
    expect(html).not.toContain('aria-modal')
    expect(html).not.toMatch(/modal/i)
  })

  test('clicking an evidence row opens that item via onOpenSource', () => {
    const ev = item()
    const opened: EvidenceItem[] = []
    const tree = (
      <EvidenceRow
        item={ev}
        selected={false}
        busy={false}
        saving={false}
        onSelect={() => undefined}
        onOpenSource={(row) => opened.push(row)}
        onChoose={() => undefined}
      />
    )
    clickTestId(tree, 'evidence-item')
    expect(opened).toEqual([ev])
  })

  test('clicking a cited claim opens that claim via onOpenSource', () => {
    const c = claim()
    const opened: Claim[] = []
    const tree = (
      <ClaimRow
        claim={c}
        checked={false}
        busy={false}
        onToggle={() => undefined}
        onOpenSource={(row) => opened.push(row)}
      />
    )
    clickTestId(tree, 'claim-source')
    expect(opened).toEqual([c])
  })
})
