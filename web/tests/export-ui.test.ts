import { describe, expect, test } from 'bun:test'
import { readdir, readFile } from 'node:fs/promises'
import { join } from 'node:path'

// Q7: export waits until M2. The prototype's "Export saved draft" control
// must not appear in the SPA as a button, menu, label, or copy.

const SRC = join(import.meta.dir, '../src')
const KEYWORD = /\bexport\s+(?:async\s+)?(?:function|class|const|let|var|type|interface|enum|default|\{|\*)/i

async function walk(dir: string): Promise<string[]> {
  const out: string[] = []
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (entry.name === 'fonts' || entry.name === 'node_modules') continue
    const path = join(dir, entry.name)
    if (entry.isDirectory()) out.push(...await walk(path))
    else if (/\.(ts|tsx|css|html)$/.test(entry.name)) out.push(path)
  }
  return out
}

/** String literals, JSX text, and CSS content after stripping export-keyword uses and comments. */
function userFacingText(source: string): string {
  const withoutComments = source
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')
  const withoutKeywords = withoutComments.replace(KEYWORD, ' ')
  return withoutKeywords
}

describe('no export entry in the UI (Q7)', () => {
  test('no button, menu, or copy mentions Export or Export saved draft', async () => {
    const files = await walk(SRC)
    const hits: string[] = []
    for (const path of files) {
      const text = userFacingText(await readFile(path, 'utf8'))
      if (/\bExport saved draft\b/i.test(text) || /(?:^|[^A-Za-z])Export(?:[^A-Za-z]|$)/.test(text)) {
        hits.push(path.slice(SRC.length + 1))
      }
    }
    expect(hits).toEqual([])
  })
})
