import { describe, expect, test } from 'bun:test'
import {
  EMPTY_WORKSPACE_HINT,
  HEALTH_CHECKING,
  HEALTH_NOT_RUNNING,
  HEALTH_OFFLINE,
  HEALTH_READY,
  OFFLINE_MESSAGE,
  SAVE_FAILURE_MESSAGE,
  SERVICE_NOT_RUNNING_MESSAGE,
  initialLoadErrorMessage,
  saveFailureMessage,
} from '../src/copy'

describe('Q5 and R1-AC3 copy is byte-exact', () => {
  test('offline message matches tech-design §7 / Q5', () => {
    expect(OFFLINE_MESSAGE).toBe(
      "You're offline. Your saved work is safe on this computer. Sending to the AI assistant will work again when you're back online.",
    )
  })

  test('save-failure message matches tech-design §7 / Q5', () => {
    expect(SAVE_FAILURE_MESSAGE).toBe(
      "We couldn't save this section. Your text is still here. Copy it somewhere safe, then try Save again.",
    )
  })

  test('service-not-running message matches ADR 0023', () => {
    expect(SERVICE_NOT_RUNNING_MESSAGE).toBe(
      "The writing workspace isn't running on this computer. Double-click Start Psychtool, then reload this page. If that doesn't help, ask the person who installed it.",
    )
  })
})

describe('initialLoadErrorMessage', () => {
  test('uses the service-not-running copy when the browser is online', () => {
    expect(initialLoadErrorMessage(true)).toBe(SERVICE_NOT_RUNNING_MESSAGE)
  })

  test('uses the Q5 offline copy when the browser is offline', () => {
    expect(initialLoadErrorMessage(false)).toBe(OFFLINE_MESSAGE)
  })
})

describe('saveFailureMessage', () => {
  test('uses the Q5 save-failure copy for a 5xx', () => {
    expect(saveFailureMessage({ status: 500, serverMessage: null })).toBe(SAVE_FAILURE_MESSAGE)
  })

  test('uses the Q5 save-failure copy for a dropped connection', () => {
    expect(saveFailureMessage({ status: 0 })).toBe(SAVE_FAILURE_MESSAGE)
  })

  test('uses the Q5 save-failure copy when no error object is available', () => {
    expect(saveFailureMessage(undefined)).toBe(SAVE_FAILURE_MESSAGE)
  })

  test('keeps an allowlisted 4xx server message (draft-filter refusal)', () => {
    const detail = 'A Summary draft cannot include diagnostic or recommendation wording.'
    expect(saveFailureMessage({ status: 400, serverMessage: detail })).toBe(detail)
  })

  test('visible status words do not contain API, JSON, or token', () => {
    const visible = [
      OFFLINE_MESSAGE,
      SAVE_FAILURE_MESSAGE,
      SERVICE_NOT_RUNNING_MESSAGE,
      EMPTY_WORKSPACE_HINT,
      HEALTH_CHECKING,
      HEALTH_READY,
      HEALTH_OFFLINE,
      HEALTH_NOT_RUNNING,
    ].join('\n')
    expect(visible).not.toMatch(/\bAPI\b/)
    expect(visible).not.toMatch(/\bJSON\b/)
    expect(visible).not.toMatch(/\btoken\b/i)
  })
})
