export type ReviewGate = 'standard' | 'licensed_clinician'
export type SectionStatus = 'empty' | 'draft' | 'needs_review' | 'approved'
export interface TemplateSection {
  id: string
  title: string
  required: boolean
  review_gate: ReviewGate
  content_types: string[]
  allowed_sources: string[]
}
export interface ReportTemplate {
  template_id: string
  version: number
  report_type: string
  title: string
  sections: TemplateSection[]
}
export interface SectionState {
  section_id: string
  title: string
  status: SectionStatus
  review_gate: ReviewGate
  required: boolean
  text: string
  claim_ids: string[]
  version: number
  reviewer?: string | null
}
export interface Claim {
  id: string
  text: string
  topic: string
  verification_status: string
  provider_role: string
}
export interface Workspace { case_id: string }
export interface Material {
  id: string
  case_id: string
  title: string
  provider: string
  date: string
  version: number
  passages: { id: string; text: string }[]
}
export interface ClaimSuggestion {
  id: string
  source_document_id: string
  source_version: number
  source_passage_id: string
  source_text: string
  text: string
  provider_role: 'self_report' | 'other_report' | 'clinician_interpretation'
  observation_setting: string
  record_time: string
  event_time: string | null
  category: string
  topic: string
}
export interface UploadResult {
  material: Material
  identifier_findings: { category: string; label: string }[]
  requires_human_review: boolean
}
export interface SourceRef { kind: 'claim' | 'material' | 'draft'; id: string; version: number }
export type EgressStatus = 'prepared' | 'approved' | 'sent' | 'invalidated'
export interface EgressRequest {
  request_id: string
  workspace_id: string
  purpose: 'section_generation' | 'draft_generation' | 'judge' | 'eval'
  data_tier: 'real' | 'synthetic'
  provider_base_url: string
  model: string
  preview: string
  source_refs: SourceRef[]
  identifier_categories: string[]
  content_hash: string
  status: EgressStatus
  approval_mode: 'human' | 'synthetic_auto' | null
  reviewer: string | null
  approval_reason: string | null
  prepared_at: string
  approved_at: string | null
  sent_at: string | null
  requires_human_review: boolean
}
export interface PrepareInput {
  template_id: string
  template_version: number
  section_id: string
  claim_ids: string[]
  instructions: string
}
export type ApprovalInput = { content_hash: string; reviewer: string } | { content_hash: string; synthetic_auto_reason: string }
export interface SendResult { request_id: string; status: 'sent'; text: string }
