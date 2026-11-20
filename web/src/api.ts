import type { ApprovalInput, EgressRequest, PrepareInput, SendResult, UploadResult } from './types'

/** Never expose an error response body: validation/provider errors may contain input. */
export class ApiError extends Error {
  readonly status: number
  constructor(status: number) {
    super(status === 0 ? 'Connection failed.' : `Request failed (${status}).`)
    this.name = 'ApiError'
    this.status = status
  }
}

export function workspaceUrl(workspaceId: string): string {
  return `/api/workspaces/${encodeURIComponent(workspaceId)}`
}

export async function apiRequest<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response
  try { response = await fetch(url, init) } catch { throw new ApiError(0) }
  if (!response.ok) throw new ApiError(response.status)
  try { return await response.json() as T } catch { throw new ApiError(0) }
}

export function jsonRequest<T>(url: string, method: 'POST' | 'PUT', body: unknown): Promise<T> {
  return apiRequest<T>(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
}

export function uploadMaterial(workspaceId: string, form: FormData): Promise<UploadResult> {
  return apiRequest(`${workspaceUrl(workspaceId)}/materials`, { method: 'POST', body: form })
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
