import { defineConfig, devices } from '@playwright/test'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

// One full-path e2e against the real backend serving the built SPA.
// The webServer below starts `uv run psychtool-server` (uvicorn on
// 127.0.0.1:8000) against a fresh temp SQLite database; the server defaults
// to the offline FakeTransport, so no API key or network access is needed.

// Playwright evaluates this config in the runner and again in each worker.
// Create the temp database once in the runner, then reuse the path so the
// correction e2e and the webServer talk to the same file.
const dbPath = process.env.PSYCHTOOL_E2E_DB_PATH
  ?? join(mkdtempSync(join(tmpdir(), 'psychtool-e2e-')), 'psychtool.db')
process.env.PSYCHTOOL_E2E_DB_PATH = dbPath

export default defineConfig({
  testDir: './e2e',
  // *.e2e.ts keeps these specs out of `bun test` discovery while staying
  // explicit for Playwright (its default testMatch would miss this suffix).
  testMatch: '**/*.e2e.ts',
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  projects: [
    {
      name: 'chromium',
      // PW_CHROMIUM_CHANNEL=chrome runs the e2e against a system Chrome
      // (for sandboxes without the downloaded Playwright browser build).
      use: {
        ...devices['Desktop Chrome'],
        ...(process.env.PW_CHROMIUM_CHANNEL
          ? { channel: process.env.PW_CHROMIUM_CHANNEL }
          : {}),
      },
    },
  ],
  use: {
    baseURL: 'http://127.0.0.1:8000',
  },
  webServer: {
    // The backend must serve the built SPA: run `bun run build` in web/ first.
    command: 'uv run psychtool-server',
    cwd: '..',
    url: 'http://127.0.0.1:8000/api/health',
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      PSYCHTOOL_DB_PATH: dbPath,
      // Playwright merges process.env into the webServer, so pin these to
      // keep a developer shell with PSYCHTOOL_TRANSPORT=http from making the
      // e2e touch the network.
      PSYCHTOOL_TRANSPORT: 'fake',
      PSYCHTOOL_DATA_TIER: 'synthetic',
    },
  },
})
