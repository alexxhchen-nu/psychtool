/** Clinician-facing copy for PT-14 (GROK-44 / R1-AC3 + R16).

The offline and save-failure strings are byte-exact with tech-design.md §7
(Q5, 2026-11-24). The service-not-running string is the R1-AC3 message
documented in ADR 0023; it is not a §7-specified sentence.
*/

export const OFFLINE_MESSAGE =
  "You're offline. Your saved work is safe on this computer. Sending to the AI assistant will work again when you're back online."

export const SAVE_FAILURE_MESSAGE =
  "We couldn't save this section. Your text is still here. Copy it somewhere safe, then try Save again."

export const SERVICE_NOT_RUNNING_MESSAGE =
  "The writing workspace isn't running on this computer. Double-click Start Psychtool, then reload this page. If that doesn't help, ask the person who installed it."

export const EMPTY_WORKSPACE_HINT =
  'Use the form above to start a new case on this computer.'

export const HEALTH_CHECKING = 'Checking…'
export const HEALTH_READY = 'Ready'
export const HEALTH_OFFLINE = 'Offline'
export const HEALTH_NOT_RUNNING = 'Not running'

/** Prefer the offline copy when the browser itself is offline. */
export function initialLoadErrorMessage(online: boolean): string {
  return online ? SERVICE_NOT_RUNNING_MESSAGE : OFFLINE_MESSAGE
}

/**
 * 4xx responses that already carry an allowlisted clinician-facing
 * `serverMessage` (the Summary / draft-filter refusals) keep that text.
 * Network failures, 5xx, and any other save error use the Q5 save-failure copy.
 */
export function saveFailureMessage(
  error: { status?: number; serverMessage?: string | null } | null | undefined,
): string {
  if (
    error
    && typeof error.status === 'number'
    && error.status >= 400
    && error.status < 500
    && error.serverMessage
  ) {
    return error.serverMessage
  }
  return SAVE_FAILURE_MESSAGE
}
