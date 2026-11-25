// PT-20 (ADR 0017): the citation line only ever formats server-returned ids.

import { describe, expect, test } from 'bun:test'

import { citedEvidenceLine } from '../src/claims'

describe('citedEvidenceLine', () => {
  test('empty list says none and never fabricates an id', () => {
    const line = citedEvidenceLine([])
    expect(line).toBe('Cites sentence evidence: none')
    expect(line).not.toContain('ev_')
  })

  test('one id is shown verbatim', () => {
    expect(citedEvidenceLine(['ev_abc123'])).toBe(
      'Cites sentence evidence: ev_abc123',
    )
  })

  test('several ids are all shown in order', () => {
    expect(citedEvidenceLine(['ev_a', 'ev_b', 'ev_c'])).toBe(
      'Cites sentence evidence: ev_a, ev_b, ev_c',
    )
  })
})
