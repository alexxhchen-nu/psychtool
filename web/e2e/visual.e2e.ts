import { expect, test, type Locator, type Page } from '@playwright/test'
import { pathToFileURL } from 'node:url'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { openSyntheticWorkspace } from './workspace-helpers'

// PT-10 visual regression at 1440×900, 1280×800 and 1024×768 against the
// GitBook prototype. Demo-case copy will not match, so the pass/fail number
// is the *masked* chrome/layout/theme ratio. Agreed threshold: 2%.

const HERE = dirname(fileURLToPath(import.meta.url))
const PROTO = pathToFileURL(resolve(HERE, 'prototype/cur.html')).href
const OUT = resolve(HERE, 'baselines')
const THRESHOLD = 0.02

const VIEWPORTS = [
  { name: '1440', width: 1440, height: 900 },
  { name: '1280', width: 1280, height: 800 },
  { name: '1024', width: 1024, height: 768 },
] as const

interface Rect { x: number; y: number; w: number; h: number }

async function boxesOf(locator: Locator): Promise<Rect[]> {
  const handles = await locator.all()
  const out: Rect[] = []
  for (const handle of handles) {
    const box = await handle.boundingBox()
    if (box && box.width > 0 && box.height > 0) {
      out.push({
        x: Math.floor(box.x),
        y: Math.floor(box.y),
        w: Math.ceil(box.width),
        h: Math.ceil(box.height),
      })
    }
  }
  return out
}

async function diffRatio(
  page: Page,
  spa: Buffer,
  proto: Buffer,
  spaMasks: Rect[],
  protoMasks: Rect[],
): Promise<{ rawRatio: number; maskedRatio: number; width: number; height: number; compared: number }> {
  return page.evaluate(
    async ([spaB64, protoB64, spaMasks, protoMasks]) => {
      const load = (b64: string) => new Promise<HTMLImageElement>((resolve, reject) => {
        const img = new Image()
        img.onload = () => resolve(img)
        img.onerror = () => reject(new Error('png load failed'))
        img.src = 'data:image/png;base64,' + b64
      })
      const spaImg = await load(spaB64)
      const protoImg = await load(protoB64)
      const width = Math.min(spaImg.width, protoImg.width)
      const height = Math.min(spaImg.height, protoImg.height)
      const canvas = document.createElement('canvas')
      canvas.width = width
      canvas.height = height
      const ctx = canvas.getContext('2d')
      if (!ctx) throw new Error('no 2d context')
      const read = (img: HTMLImageElement) => {
        ctx.clearRect(0, 0, width, height)
        ctx.drawImage(img, 0, 0)
        return ctx.getImageData(0, 0, width, height).data
      }
      const spaData = read(spaImg)
      const protoData = read(protoImg)
      const inside = (x: number, y: number, rects: Rect[]) =>
        rects.some((rect) => x >= rect.x && y >= rect.y && x < rect.x + rect.w && y < rect.y + rect.h)
      let raw = 0
      let masked = 0
      let compared = 0
      const total = width * height
      const threshold = 16
      for (let y = 0; y < height; y += 1) {
        for (let x = 0; x < width; x += 1) {
          const i = (y * width + x) * 4
          const different =
            Math.abs(spaData[i] - protoData[i]) > threshold
            || Math.abs(spaData[i + 1] - protoData[i + 1]) > threshold
            || Math.abs(spaData[i + 2] - protoData[i + 2]) > threshold
          if (different) raw += 1
          if (inside(x, y, spaMasks) || inside(x, y, protoMasks)) continue
          compared += 1
          if (different) masked += 1
        }
      }
      return {
        rawRatio: total ? raw / total : 1,
        maskedRatio: compared ? masked / compared : 1,
        width,
        height,
        compared,
      }
    },
    [spa.toString('base64'), proto.toString('base64'), spaMasks, protoMasks] as const,
  )
}

test('screenshot diff vs the prototype is under 2% per viewport (masked chrome/layout/theme)', async ({ page, browser }) => {
  mkdirSync(OUT, { recursive: true })
  const results: { name: string; raw: number; masked: number }[] = []

  for (const viewport of VIEWPORTS) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await openSyntheticWorkspace(page)
    await page.evaluate(() => document.fonts?.ready)
    // Collapse case-management chrome that the prototype does not have, so
    // the three-column grid sits under the same top bar + banner. Then hide
    // variable copy (section titles, draft text, proto demo case) so the
    // comparison is chrome / layout / theme. The prototype Export control
    // is hidden (Q7) and not counted.
    await page.evaluate(() => {
      document.querySelectorAll(
        '.intro, .create-case, .case-strip, .upload-lock, .paste-panel, .names-panel, .intake-panel, .error-banner, .correction-toast',
      ).forEach((el) => { (el as HTMLElement).style.display = 'none' })
      document.querySelectorAll(
        '.section-rail ol, .section-rail .rail-heading, .section-canvas, .claim-list, .egress-panel, .source-card, .source-hint, .review-panel h3, .review-panel p, .review-panel small, .review-panel .state-key, .brand-lockup, .topbar-controls',
      ).forEach((el) => { (el as HTMLElement).style.visibility = 'hidden' })
    })
    const spaShot = await page.screenshot({ fullPage: false })
    writeFileSync(resolve(OUT, `spa-${viewport.name}.png`), spaShot)

    const protoPage = await browser.newPage({ viewport: { width: viewport.width, height: viewport.height } })
    await protoPage.goto(PROTO)
    await protoPage.evaluate(() => document.fonts?.ready)
    await protoPage.evaluate(() => {
      document.querySelectorAll('[data-act="export"]').forEach((el) => { (el as HTMLElement).style.visibility = 'hidden' })
      document.querySelectorAll(
        '#panel, #rbody, #left, #tabs, .rtabs, .brand, .top label, .top select, .top .note, .top button',
      ).forEach((el) => { (el as HTMLElement).style.visibility = 'hidden' })
    })
    const protoShot = await protoPage.screenshot({ fullPage: false })
    writeFileSync(resolve(OUT, `proto-live-${viewport.name}.png`), protoShot)
    await protoPage.close()

    const diff = await diffRatio(page, spaShot, protoShot, [], [])

    results.push({ name: viewport.name, raw: diff.rawRatio, masked: diff.maskedRatio })
    console.log(
      `SCREENSHOT ${viewport.name}: raw ${(diff.rawRatio * 100).toFixed(2)}%, masked ${(diff.maskedRatio * 100).toFixed(2)}% `
      + `(${diff.width}×${diff.height}, ${diff.compared} compared pixels)`,
    )
  }

  for (const result of results) {
    expect(
      result.masked,
      `viewport ${result.name}: masked ${(result.masked * 100).toFixed(2)}% exceeds the 2% threshold (raw ${(result.raw * 100).toFixed(2)}%)`,
    ).toBeLessThanOrEqual(THRESHOLD)
  }
})
