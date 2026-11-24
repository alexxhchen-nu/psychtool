import type { ApprovalInput, EgressRequest, PasteMaterialInput, PrepareInput, SendResult, UploadResult, Workspace } from './types'

/** Never expose an error response body: validation/provider errors may contain input. */
export class ApiError extends Error {
  readonly status: number
  constructor(status: number) {
    super(status === 0 ? 'Connection failed.' : `Request failed (${status}).`)
    this.name = 'ApiError'
    this.status = status
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

export function uploadMaterial(workspaceId: string, form: FormData): Promise<UploadResult> {
  return apiRequest(`${workspaceUrl(workspaceId)}/materials`, { method: 'POST', body: form })
}

export function createCase(caseId: string): Promise<Workspace> {
  return jsonRequest('/api/workspaces', 'POST', { case_id: caseId })
}

export function pasteMaterial(workspaceId: string, input: PasteMaterialInput): Promise<UploadResult> {
  return jsonRequest(`${workspaceUrl(workspaceId)}/materials/paste`, 'POST', input)
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

export function approveEgress(workspaceId: string, requestId: string, input: ApprovalInput): Promise<EgressRequest> {
  const body = 'reviewer' in input
    ? { content_hash: input.content_hash, reviewer: input.reviewer }
    : { content_hash: input.content_hash, synthetic_auto_reason: input.synthetic_auto_reason }
  return jsonRequest(`${workspaceUrl(workspaceId)}/egress/${encodeURIComponent(requestId)}/approve`, 'POST', body)
}

export function sendEgress(workspaceId: string, requestId: string): Promise<SendResult> {
  return apiRequest(`${workspaceUrl(workspaceId)}/egress/${encodeURIComponent(requestId)}/send`, { method: 'POST' })
}
