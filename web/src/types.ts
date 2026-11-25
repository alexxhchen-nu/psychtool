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
  /** R13 (ADR 0013): how many paragraphs the protected-content screen held back. */
  blocked_paragraphs?: number
  /** Present only when blocked_paragraphs > 0; the server's fixed message. */
  blocked_reason?: string
}
export interface SourceRef { kind: 'claim' | 'material' | 'draft'; id: string; version: number }
export type EgressStatus = 'prepared' | 'approved' | 'sent' | 'invalidated' | 'send_interrupted'
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
/** R5 (PT-07 / ADR 0015): the 8 allowlisted category keys. */
export type EvidenceCategory =
  | 'family_history'
  | 'medical_history'
  | 'test_results'
  | 'behavioral_observations'
  | 'development_school'
  | 'daily_living'
  | 'other'
  | 'uncategorized'
/** R5: the 6 allowlisted source-role keys, recorded separately from category. */
export type EvidenceRole =
  | 'school'
  | 'caregiver'
  | 'medical_record'
  | 'clinician'
  | 'client'
  | 'to_confirm'
export interface EvidenceItem {
  id: string
  quote: string
  material_id: string
  material_title: string
  material_version: number
  passage_id: string
  paragraph: number
  /** Code-point offsets into the passage text (see ADR 0014). */
  start: number
  end: number
  /** Effective category: her choice when set, otherwise the suggestion. */
  category: EvidenceCategory
  category_label: string
  /** Short reason quoting the matched keyword (<= 140 chars; R5-AC1). */
  category_reason: string
  category_set_by: 'clinician' | 'suggestion'
  role: EvidenceRole
  role_label: string
  role_reason: string
  role_set_by: 'clinician' | 'suggestion'
  /** Superseded by newer rules but kept because it carries her correction. */
  kept_because_corrected: boolean
}
export interface EvidenceResponse {
  extractor: string
  rules_version: string
  items: EvidenceItem[]
  needs_extraction: boolean
}
export interface EvidenceRefreshResult {
  extractor: string
  rules_version: string
  materials: Record<string, number>
  /** Candidates dropped by the span check during THIS refresh. */
  dropped: number
  needs_extraction: boolean
}
/** Fields present on a PUT; omitted fields stay untouched. */
export interface EvidenceChoiceInput {
  category?: EvidenceCategory | null
  role?: EvidenceRole | null
}
export interface EvidenceChoiceResult {
  id: string
  category: EvidenceCategory
  category_label: string
  category_reason: string
  category_set_by: 'clinician' | 'suggestion'
  role: EvidenceRole
  role_label: string
  role_reason: string
  role_set_by: 'clinician' | 'suggestion'
}
export interface PasteMaterialInput {
  material_id: string
  title: string
  provider: string
  date: string
  text: string
  synthetic_confirmed: boolean
}
