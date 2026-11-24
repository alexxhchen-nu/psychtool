import type { ApprovalInput, EgressRequest, EvidenceResponse, PasteMaterialInput, PrepareInput, SendResult, UploadResult, Workspace } from './types'

/** Never expose an error response body: validation/provider errors may contain input. */
export class ApiError extends Error {
  readonly status: number
  /**
   * Fixed server rejection text, present only when the server sent its
   * allowlisted upload-rejection body ({detail, reason}). The detail is a
   * constant chosen server-side and never quotes user input, so showing it
   * verbatim cannot leak material text.
   */
  readonly serverMessage: string | null
  constructor(status: number, serverMessage: string | null = null) {
    super(status === 0 ? 'Connection failed.' : `Request failed (${status}).`)
    this.name = 'ApiError'
    this.status = status
    this.serverMessage = serverMessage
  }
}

// The server injects the per-start session token into the served index.html
// as <meta name="psychtool-session" content="...">. It is read once and sent
// as X-Psychtool-Token on every API call; if the meta tag is absent (e.g.
// the Vite dev server), requests go out without it and the server answers
// 401 unless the dev proxy adds the header.
const SESSION_HEADER = 'X-Psychtool-Token'
let cachedToken: string | null | undefined

export function sessionToken(): string | null {
  if (cachedToken !== undefined) return cachedToken
  cachedToken = null
  try {
    const meta = document.querySelector<HTMLMetaElement>(`meta[name="psychtool-session"]`)
    const content = meta?.content?.trim()
    if (content) cachedToken = content
  } catch { cachedToken = null }
  return cachedToken
}

/** Test hook: forget the cached token so the next call re-reads the DOM. */
export function resetSessionTokenCache(): void {
  cachedToken = undefined
}

function withSessionHeader(init?: RequestInit): RequestInit {
  const token = sessionToken()
  if (!token) return init ?? {}
  const headers = new Headers(init?.headers)
  headers.set(SESSION_HEADER, token)
  return { ...init, headers }
}

export function workspaceUrl(workspaceId: string): string {
  return `/api/workspaces/${encodeURIComponent(workspaceId)}`
}

export async function apiRequest<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response
  try { response = await fetch(url, withSessionHeader(init)) } catch { throw new ApiError(0) }
  if (!response.ok) throw new ApiError(response.status)
  try { return await response.json() as T } catch { throw new ApiError(0) }
}

export function jsonRequest<T>(url: string, method: 'POST' | 'PUT', body: unknown): Promise<T> {
  return apiRequest<T>(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
}

/**
 * Requests with the server's fixed rejection reason surfaced. Only the
 * upload and paste endpoints return the allowlisted {detail, reason} body
 * (type/size rejections and the R13 protected-content reasons); every other
 * API error stays an opaque status (see ApiError).
 */
async function reasonedRequest(url: string, init: RequestInit): Promise<UploadResult> {
  let response: Response
  try { response = await fetch(url, withSessionHeader(init)) } catch { throw new ApiError(0) }
  if (!response.ok) {
    let serverMessage: string | null = null
    try {
      const body = await response.json() as { detail?: unknown; reason?: unknown }
      if (typeof body.detail === 'string' && typeof body.reason === 'string') {
        serverMessage = body.detail
      }
    } catch { serverMessage = null }
    throw new ApiError(response.status, serverMessage)
  }
  try { return await response.json() as UploadResult } catch { throw new ApiError(0) }
}

async function uploadRequest(url: string, form: FormData): Promise<UploadResult> {
  return reasonedRequest(url, { method: 'POST', body: form })
}

export function uploadMaterial(workspaceId: string, form: FormData): Promise<UploadResult> {
  return uploadRequest(`${workspaceUrl(workspaceId)}/materials`, form)
}

export function createCase(caseId: string): Promise<Workspace> {
  return jsonRequest('/api/workspaces', 'POST', { case_id: caseId })
}

export function confirmSynthetic(workspaceId: string): Promise<{ case_id: string; synthetic_confirmed: boolean }> {
  return apiRequest(`${workspaceUrl(workspaceId)}/synthetic-confirmation`, { method: 'POST' })
}

export function getWorkspace(workspaceId: string): Promise<{ case_id: string; synthetic_confirmed: boolean }> {
  return apiRequest(workspaceUrl(workspaceId))
}

export function pasteMaterial(workspaceId: string, input: PasteMaterialInput): Promise<UploadResult> {
  return reasonedRequest(`${workspaceUrl(workspaceId)}/materials/paste`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}

export function prepareEgress(workspaceId: string, input: PrepareInput): Promise<EgressRequest> {
  return jsonRequest(`${workspaceUrl(workspaceId)}/egress/prepare`, 'POST', {
    template_id: input.template_id,
    template_version: input.template_version,
    section_id: input.section_id,
    claim_ids: input.claim_ids,
    instructions: input.instructions,
    purpose: 'section_generation',
  })
}

export function getEgress(workspaceId: string, requestId: string): Promise<EgressRequest> {
  return apiRequest(`${workspaceUrl(workspaceId)}/egress/${encodeURIComponent(requestId)}`)
}

export function getEvidence(workspaceId: string): Promise<EvidenceResponse> {
  return apiRequest(`${workspaceUrl(workspaceId)}/evidence`)
}

export function approveEgress(workspaceId: string, requestId: string, input: ApprovalInput): Promise<EgressRequest> {
  const body = 'reviewer' in input
    ? { content_hash: input.content_hash, reviewer: input.reviewer }
    : { content_hash: input.content_hash, synthetic_auto_reason: input.synthetic_auto_reason }
  return jsonRequest(`${workspaceUrl(workspaceId)}/egress/${encodeURIComponent(requestId)}/approve`, 'POST', body)
}

export function sendEgress(workspaceId: string, requestId: string): Promise<SendResult> {
  return apiRequest(`${workspaceUrl(workspaceId)}/egress/${encodeURIComponent(requestId)}/send`, { method: 'POST' })
}
