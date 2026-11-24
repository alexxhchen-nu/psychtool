// PT-06 (R4): pure evidence helpers. Offsets from the server are Unicode
// code-point indices into a passage's text (see ADR 0014); JavaScript string
// slicing is UTF-16 based, so everything here goes through Array.from to
// keep Python and the browser in agreement even with astral characters.

export interface HighlightParts {
  before: string
  mark: string
  after: string
}

/**
 * Split `text` around the code-point range [start, end) so the mark slice
 * equals `Array.from(text).slice(start, end).join('')`.
 */
export function highlightParts(text: string, start: number, end: number): HighlightParts {
  const codePoints = Array.from(text)
  const safeStart = Math.max(0, Math.min(start, codePoints.length))
  const safeEnd = Math.max(safeStart, Math.min(end, codePoints.length))
  return {
    before: codePoints.slice(0, safeStart).join(''),
    mark: codePoints.slice(safeStart, safeEnd).join(''),
    after: codePoints.slice(safeEnd).join(''),
  }
}

/** Format the source line shown under each evidence quote. */
export function evidenceSourceLine(materialTitle: string, version: number, paragraph: number): string {
  return `${materialTitle} · version ${version} · paragraph ${paragraph}`
}

/** Fixed notice shown only when candidates were dropped (never repaired). */
export function droppedNotice(dropped: number): string | null {
  if (dropped <= 0) return null
  return `${dropped} candidate${dropped === 1 ? '' : 's'} were dropped because the quote did not match the source exactly.`
}
