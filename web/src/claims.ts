// PT-20 (ADR 0017): pure claim-citation helpers. Sentence evidence is the
// only source a claim cites; these helpers only format the ids the server
// returned — the UI never invents an id.

/** Format the citation line shown on each intake suggestion card. */
export function citedEvidenceLine(evidenceIds: string[]): string {
  if (!evidenceIds.length) return 'Cites sentence evidence: none'
  return `Cites sentence evidence: ${evidenceIds.join(', ')}`
}
