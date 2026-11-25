import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { apiRequest, createCase, getWorkspace, jsonRequest, workspaceUrl } from './api'
import type { Claim, ClaimSuggestion, EvidenceInvalidation, Material, ReportTemplate, SectionState, SectionStatus, TemplateSection, UploadResult, Workspace } from './types'
import { validateCaseId } from './case-form'
import { citedEvidenceLine } from './claims'
import { applyInvalidationToSections } from './correction'
import MaterialUploadPanel from './components/MaterialUploadPanel'
import PasteMaterialPanel from './components/PasteMaterialPanel'
import DimensionsPanel from './components/DimensionsPanel'
import EgressReviewPanel from './components/EgressReviewPanel'
import EvidencePanel from './components/EvidencePanel'
import ClaimRow from './components/ClaimRow'
import ReportColumns from './components/ReportColumns'
import SourceCard from './components/SourceCard'
import { sourceCardFromClaim, sourceCardFromEvidence } from './source-card'
import type { SourceCardModel } from './source-card'
import {
  CLINICIAN_AUTHORED_EMPTY,
  CLINICIAN_AUTHORED_NOTICE,
  applyGeneratedText,
  canApproveSection,
  draftFromSectionState,
  editDraftText,
  saveBarPrimaryAction,
  saveStateLabel,
  sectionUsesGeneration,
  setDraftStatus,
  toggleDraftClaim,
} from './section-editor'
import type { EditorDraft } from './section-editor'
import './App.css'

export const PRIVACY_BANNER = 'Please note: This prototype is not HIPAA compliant yet. Do not enter real patient information. Use only synthetic or separately approved practice materials.'

const STATUS_LABELS: Record<SectionStatus, string> = { empty: 'Empty', draft: 'Draft', needs_review: 'Needs review', approved: 'Approved' }
const STATUS_ORDER: SectionStatus[] = ['empty', 'draft', 'needs_review', 'approved']

// PT-10: every status tag pairs colour with a glyph (✓ / ? / !) so the
// state is never carried by colour alone.
const STATUS_GLYPHS: Record<SectionStatus, string> = { empty: '', draft: '!', needs_review: '?', approved: '✓' }

function App() {
  const [templates, setTemplates] = useState<ReportTemplate[]>([])
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [templateId, setTemplateId] = useState('')
  const [workspaceId, setWorkspaceId] = useState('')
  const [health, setHealth] = useState('Checking API')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    let active = true
    Promise.all([
      apiRequest<{ version: string }>('/api/health'),
      apiRequest<ReportTemplate[]>('/api/templates'),
      apiRequest<Workspace[]>('/api/workspaces'),
    ]).then(([healthData, templateData, workspaceData]) => {
      if (!active) return
      setHealth(`API v${healthData.version}`)
      setTemplates(templateData)
      setWorkspaces(workspaceData)
      setTemplateId(templateData[0]?.template_id ?? '')
      setWorkspaceId(workspaceData[0]?.case_id ?? '')
    }).catch(() => {
      if (!active) return
      setHealth('API offline')
      setError('Start the psychtool server, then reload to load templates and workspaces.')
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])
  const template = templates.find((item) => item.template_id === templateId)
  const caseCreated = useCallback((created: Workspace) => {
    setWorkspaces((items) => [...items.filter((item) => item.case_id !== created.case_id), created]
      .sort((a, b) => a.case_id.localeCompare(b.case_id)))
    setWorkspaceId(created.case_id)
  }, [])
  return <div className="app-shell">
    <header className="topbar">
      <div className="brand-lockup"><span className="brand-mark">P</span><div><h1>psychtool</h1><p className="brand-description">Source-traceable writing</p></div></div>
      <div className="topbar-controls">
        <label className="inline-picker"><span>Case</span>
          <select value={workspaceId} disabled={busy || loading} onChange={(event) => setWorkspaceId(event.target.value)}>
            {!workspaces.length && <option value="">No workspaces</option>}
            {workspaces.map((item) => <option key={item.case_id} value={item.case_id}>{item.case_id}</option>)}
          </select>
        </label>
        <div className="system-status" role="status">{health}</div>
      </div>
    </header>
    <div className="privacy-banner" role="note">{PRIVACY_BANNER}</div>
    <main className="workspace">
      <section className="intro">
        <div><h2>Your report, section by section.</h2><p>Review sources, approve the exact model request, then edit and save. Request approval and section approval are separate decisions.</p></div>
        <label className="template-picker"><span>Report template</span>
          <select value={templateId} disabled={busy || loading} onChange={(event) => setTemplateId(event.target.value)}>
            {templates.map((item) => <option key={item.template_id} value={item.template_id}>{item.title}</option>)}
          </select>
        </label>
      </section>
      {error && <div className="error-banner" role="alert">{error}</div>}
      {loading && <p role="status">Loading workspace…</p>}
      {!loading && !error && <CreateCasePanel onCreated={caseCreated} />}
      {workspaceId && template && <Workbench key={`${workspaceId}/${template.template_id}/${template.version}`} workspaceId={workspaceId} template={template} onBusyChange={setBusy} />}
      {!loading && !error && !workspaceId && <section className="empty-workspace"><h3>Create a case to begin.</h3><p>Use the form above, or run <code>psychtool init &lt;path&gt; --case-id &lt;id&gt;</code> and point the server at it via <code>PSYCHTOOL_WORKSPACES_DIR</code>.</p></section>}
    </main>
  </div>
}

function CreateCasePanel({ onCreated }: { onCreated: (workspace: Workspace) => void }) {
  const [caseId, setCaseId] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const invalid = validateCaseId(caseId)
    if (invalid) { setError(invalid); return }
    setBusy(true); setError('')
    try {
      const created = await createCase(caseId)
      setCaseId('')
      onCreated(created)
    } catch {
      setError('Could not create the case. The ID may already exist or be invalid.')
    } finally {
      setBusy(false)
    }
  }
  return <section className="create-case" aria-label="Create a case">
    <form onSubmit={submit} noValidate>
      <label className="field-label" htmlFor="new-case-id">New case ID
        <input id="new-case-id" className="text-input" value={caseId} maxLength={64} autoCapitalize="off" autoComplete="off" spellCheck={false} disabled={busy} onChange={(event) => setCaseId(event.target.value)} placeholder="e.g. demo-case-1" />
      </label>
      <button className="secondary-button" type="submit" disabled={busy || !caseId}>Create case</button>
    </form>
    {error && <p className="error-banner" role="alert">{error}</p>}
  </section>
}

interface WorkbenchProps { workspaceId: string; template: ReportTemplate; onBusyChange: (busy: boolean) => void }

function Workbench({ workspaceId, template, onBusyChange }: WorkbenchProps) {
  const [sections, setSections] = useState<SectionState[]>([])
  const [claims, setClaims] = useState<Claim[]>([])
  const [materials, setMaterials] = useState<Material[]>([])
  const [names, setNames] = useState<string[]>([])
  const [namesText, setNamesText] = useState('')
  const [selectedId, setSelectedId] = useState(template.sections[0]?.id ?? '')
  const [materialId, setMaterialId] = useState('')
  const [providerRole, setProviderRole] = useState<ClaimSuggestion['provider_role']>('self_report')
  const [suggestions, setSuggestions] = useState<ClaimSuggestion[]>([])
  const [suggestionsLoaded, setSuggestionsLoaded] = useState(false)
  const [showUpload, setShowUpload] = useState(false)
  const [showPaste, setShowPaste] = useState(false)
  const [showIntake, setShowIntake] = useState(false)
  const [showNames, setShowNames] = useState(false)
  const [showEvidence, setShowEvidence] = useState(false)
  const [showDimensions, setShowDimensions] = useState(false)
  const [error, setError] = useState('')
  const [ready, setReady] = useState(false)
  const [busy, setBusy] = useState(false)
  const [sourceRevision, setSourceRevision] = useState(0)
  const [syntheticConfirmed, setSyntheticConfirmed] = useState(false)
  // PT-09 (R6 / ADR 0018): the exact server toast after a correction. The
  // toast is rendered verbatim; the client never invents counts.
  const [correctionToast, setCorrectionToast] = useState('')
  // PT-10: one selected source for the right column. Selecting a section
  // clears it; the card never replaces the editor with a modal.
  const [sourceCard, setSourceCard] = useState<SourceCardModel | null>(null)
  const alive = useRef(false)
  const mutation = useRef(false)
  const base = workspaceUrl(workspaceId)
  const changeBusy = useCallback((value: boolean) => { mutation.current = value; setBusy(value); onBusyChange(value) }, [onBusyChange])

  // R6: a correction in the Evidence or Dimensions panel cascades on the
  // server in one transaction. Here we only (1) show the server's toast,
  // (2) flip the status pill of an open APPROVED section the server returned
  // to needs_review, and (3) bump sourceRevision so the egress panel notices
  // an invalidated request. The section editor's textarea value is local
  // state and is NEVER rewritten from here.
  const correctionApplied = useCallback((toast: string, invalidation: EvidenceInvalidation) => {
    if (!alive.current) return
    setCorrectionToast(toast)
    setSections((items) => applyInvalidationToSections(items, invalidation))
    if (invalidation.egress.length > 0) setSourceRevision((value) => value + 1)
  }, [])

  useEffect(() => {
    alive.current = true
    let active = true
    Promise.all([
      apiRequest<SectionState[]>(`${base}/sections?template_id=${encodeURIComponent(template.template_id)}`),
      apiRequest<Claim[]>(`${base}/claims`), apiRequest<Material[]>(`${base}/materials`), apiRequest<{ names: string[] }>(`${base}/names`),
      getWorkspace(workspaceId),
    ]).then(([states, claimData, materialData, nameData, detail]) => {
      if (!active) return
      setSections(states); setClaims(claimData); setMaterials(materialData)
      setMaterialId(materialData[0]?.id ?? '')
      setNames(nameData.names); setNamesText(nameData.names.join('\n')); setReady(true)
      setSyntheticConfirmed(detail.synthetic_confirmed)
    }).catch(() => { if (active) setError('Could not load the case. Reload to try again.') })
    return () => { active = false; alive.current = false }
  }, [base, template.template_id, workspaceId])

  async function refreshSources() {
    const [claimData, materialData] = await Promise.all([apiRequest<Claim[]>(`${base}/claims`), apiRequest<Material[]>(`${base}/materials`)])
    if (!alive.current) return
    setClaims(claimData); setMaterials(materialData)
  }
  async function uploaded(result: UploadResult) {
    if (!alive.current) return
    setSourceRevision((value) => value + 1)
    setSuggestions([]); setSuggestionsLoaded(false)
    // Keep the successful upload selectable even if a subsequent list refresh fails.
    setMaterials((items) => [...items.filter((item) => item.id !== result.material.id), result.material])
    setMaterialId(result.material.id)
    await refreshSources()
  }
  function reviewMaterial(id: string) {
    setMaterialId(id); setSuggestions([]); setSuggestionsLoaded(false); setShowIntake(true); setShowUpload(false); setShowPaste(false)
  }
  async function runMutation(action: () => Promise<void>, failure: string) {
    if (mutation.current) return
    changeBusy(true); setError('')
    try { await action() } catch { if (alive.current) setError(failure) }
    finally { if (alive.current) changeBusy(false) }
  }
  function saveNames() {
    void runMutation(async () => {
      const result = await jsonRequest<{ names: string[] }>(`${base}/names`, 'PUT', { names: namesText.split('\n').map((name) => name.trim()).filter(Boolean) })
      if (!alive.current) return
      setNames(result.names); setNamesText(result.names.join('\n')); setSourceRevision((value) => value + 1)
    }, 'Could not save identifying names. Review the entries and try again.')
  }
  function loadSuggestions() {
    if (!materialId) return
    void runMutation(async () => {
      const items = await apiRequest<ClaimSuggestion[]>(`${base}/materials/${encodeURIComponent(materialId)}/suggestions?provider_role=${encodeURIComponent(providerRole)}`)
      if (alive.current) { setSuggestions(items); setSuggestionsLoaded(true) }
    }, 'Could not read intake passages. Check the selected material and source role.')
  }
  function acceptSuggestion(suggestion: ClaimSuggestion) {
    void runMutation(async () => {
      await jsonRequest(`${base}/claims`, 'POST', suggestion)
      if (!alive.current) return
      setSuggestions((items) => items.filter((item) => item.id !== suggestion.id))
      setSourceRevision((value) => value + 1)
      await refreshSources()
    }, 'Could not complete claim acceptance or refresh the list. Reload to check the saved state before trying again.')
  }
  function updateSuggestion(index: number, patch: Partial<ClaimSuggestion>) {
    setSuggestions((items) => items.map((item, position) => position === index ? { ...item, ...patch } : item))
  }
  const selected = template.sections.find((section) => section.id === selectedId)
  const selectedState = sections.find((section) => section.section_id === selectedId)
  const approved = sections.filter((section) => section.status === 'approved').length
  return <>
    <section className="case-strip">
      <div className="case-meta"><span className="case-id">{workspaceId}</span><span>{materials.length} materials</span><span>{claims.length} claims</span><span>{approved}/{template.sections.length} sections approved</span></div>
      <div className="case-actions">
        <button className="ghost-button" disabled={busy || !ready} aria-expanded={showUpload} onClick={() => { setShowUpload(!showUpload); setShowPaste(false) }}>Upload material</button>
        <button className="ghost-button" disabled={busy || !ready} aria-expanded={showPaste} onClick={() => { setShowPaste(!showPaste); setShowUpload(false) }}>Paste synthetic text</button>
        <button className="ghost-button" disabled={busy || !ready} aria-expanded={showIntake} onClick={() => setShowIntake(!showIntake)}>Review intake claims</button>
        <button className="ghost-button" disabled={busy || !ready} aria-expanded={showEvidence} onClick={() => setShowEvidence(!showEvidence)}>Evidence</button>
        <button className="ghost-button" disabled={busy || !ready} aria-expanded={showDimensions} onClick={() => setShowDimensions(!showDimensions)}>Dimensions</button>
        <button className="ghost-button" disabled={busy || !ready} aria-expanded={showNames} onClick={() => setShowNames(!showNames)}>Identifying info</button>
      </div>
    </section>
    {error && <div className="error-banner" role="alert">{error}</div>}
    {correctionToast && <div className="correction-toast" role="status" data-testid="correction-toast">{correctionToast}</div>}
    {!ready && !error && <p role="status">Loading case…</p>}
    {ready && <div hidden={!showUpload}><fieldset className="upload-lock" disabled={busy}><MaterialUploadPanel workspaceId={workspaceId} confirmed={syntheticConfirmed} onConfirmed={() => setSyntheticConfirmed(true)} onUploaded={uploaded} onReview={reviewMaterial} onBusyChange={changeBusy} /></fieldset></div>}
    {ready && showPaste && <fieldset className="upload-lock" disabled={busy}><PasteMaterialPanel workspaceId={workspaceId} onPasted={uploaded} onReview={reviewMaterial} onBusyChange={changeBusy} /></fieldset>}
    {showIntake && <section className="names-panel intake-panel" aria-label="Intake claim review">
      <div className="names-panel-copy"><h3>Review each source passage.</h3><p>Assign topic, category and attribution before accepting. These are passage candidates, not diagnostic conclusions.</p></div>
      <div>
        <label className="field-label">Material<select className="select-input" disabled={busy} value={materialId} onChange={(event) => { setMaterialId(event.target.value); setSuggestions([]); setSuggestionsLoaded(false) }}>
          {!materials.length && <option value="">Upload a material first</option>}
          {materials.map((item) => <option key={item.id} value={item.id}>{item.title} · v{item.version}</option>)}
        </select></label>
        <label className="field-label">Source role<select className="select-input" disabled={busy} value={providerRole} onChange={(event) => { setProviderRole(event.target.value as ClaimSuggestion['provider_role']); setSuggestions([]); setSuggestionsLoaded(false) }}>
          <option value="self_report">Self report</option><option value="other_report">Other report</option><option value="clinician_interpretation">Clinician interpretation</option>
        </select></label>
        <button className="primary-button" disabled={busy || !materialId} aria-busy={busy} onClick={loadSuggestions}>Create candidates</button>
      </div>
      <div className="intake-suggestions">
        {suggestionsLoaded && !suggestions.length && <p role="status">No remaining candidates. Accepted claims are available in the section editor.</p>}
        {suggestions.map((item, index) => <div className="intake-card" key={item.id}>
          <p className="field-label">{item.source_document_id} v{item.source_version} / {item.source_passage_id}</p><p>{item.source_text}</p>
          <p className="field-label" data-testid="cited-evidence-ids">{citedEvidenceLine(item.evidence_ids)}</p>
          <label className="field-label">Claim text<textarea className="editor-input" value={item.text} disabled={busy} onChange={(event) => updateSuggestion(index, { text: event.target.value })} /></label>
          <div className="editor-controls"><label className="field-label">Topic<input className="text-input" disabled={busy} value={item.topic} onChange={(event) => updateSuggestion(index, { topic: event.target.value })} /></label>
            <label className="field-label">Category<input className="text-input" disabled={busy} value={item.category} onChange={(event) => updateSuggestion(index, { category: event.target.value })} /></label></div>
          <button className="primary-button" disabled={busy || !item.text.trim() || !item.topic.trim() || !item.category.trim()} onClick={() => acceptSuggestion(item)}>Accept claim</button>
        </div>)}
      </div>
    </section>}
    {showNames && <section className="names-panel">
      <div className="names-panel-copy"><h3>Names used for identifier detection.</h3><p>Entries are saved to the psychtool server. Add one name per line before uploading materials or preparing requests. Automatic detection can miss identifiers; inspect every request preview.</p></div>
      <label className="field-label">Identifying names ({names.length} saved)<textarea className="names-input" rows={5} value={namesText} disabled={busy} onChange={(event) => setNamesText(event.target.value)} /></label>
      <button className="primary-button" disabled={busy} onClick={saveNames}>Save names</button>
    </section>}
    {ready && showEvidence && <EvidencePanel key={workspaceId} workspaceId={workspaceId} materials={materials} busy={busy} onCorrection={correctionApplied} onOpenSource={(item) => setSourceCard(sourceCardFromEvidence(item))} />}
    {ready && showDimensions && <DimensionsPanel key={workspaceId} workspaceId={workspaceId} materials={materials} busy={busy} syntheticConfirmed={syntheticConfirmed} onCorrection={correctionApplied} />}
    {ready && selected && selectedState && <ReportColumns
      rail={<aside className="section-rail" aria-label="Report sections"><div className="rail-heading"><span>Report sections</span><strong>{template.sections.length} sections</strong></div>
        <ol>{template.sections.map((section, index) => {
          const status = sections.find((state) => state.section_id === section.id)?.status ?? 'empty'
          return <li key={section.id}><button className={section.id === selectedId ? 'section-link active' : 'section-link'} disabled={busy} aria-current={section.id === selectedId ? 'step' : undefined} aria-label={`${section.title}, ${STATUS_LABELS[status]}`} onClick={() => { setSelectedId(section.id); setSourceCard(null) }}>
            <span className="section-number">{String(index + 1).padStart(2, '0')}</span><span className="section-name">{section.title}</span><span className={`status-tag ${status}`} aria-hidden="true">{STATUS_GLYPHS[status]}</span>
          </button></li>
        })}</ol>
      </aside>}
      editor={<SectionEditor workspaceId={workspaceId} template={template} section={selected} initial={selectedState} claims={claims} sourceRevision={sourceRevision} busy={busy} onBusyChange={changeBusy} onOpenSourceClaim={(claim) => setSourceCard(sourceCardFromClaim(claim, materials))} onSaved={(state) => setSections((items) => items.map((item) => item.section_id === state.section_id ? state : item))} />}
      source={<>
        <h3>{approved} of {template.sections.length} approved</h3>
        {sourceCard
          ? <SourceCard card={sourceCard} onClose={() => setSourceCard(null)} />
          : <p className="source-hint" data-testid="source-card-hint">Select a claim or an evidence item to see its source here. The editor stays open.</p>}
        <p>Model requests and report sections have separate approval steps. Generated text stays unsaved until you save it.</p>
        <div className="state-key">{STATUS_ORDER.map((status) => <div key={status}><span className={`status-tag ${status}`} aria-hidden="true">{STATUS_GLYPHS[status]}</span>{STATUS_LABELS[status]}</div>)}</div>
        <small>Development workspace for synthetic or public materials. Reviewer names are labels, not verified identities. These controls do not establish HIPAA compliance.</small>
      </>}
    />}
  </>
}

interface EditorProps extends WorkbenchProps {
  section: TemplateSection
  initial: SectionState
  claims: Claim[]
  sourceRevision: number
  busy: boolean
  onSaved: (state: SectionState) => void
  onOpenSourceClaim: (claim: Claim) => void
}
function SectionEditor({ workspaceId, template, section, initial, claims, sourceRevision, busy, onBusyChange, onSaved, onOpenSourceClaim }: EditorProps) {
  // R9-AC1/AC2: drafts are kept per section id so switching away and back
  // does not drop unsaved text. The editor itself is NOT keyed by section id.
  const [forms, setForms] = useState<Record<string, EditorDraft>>(() => ({
    [initial.section_id]: draftFromSectionState(initial),
  }))
  const [dirty, setDirty] = useState<Record<string, boolean>>({})
  const [versions, setVersions] = useState<Record<string, number>>({ [initial.section_id]: initial.version })
  const [messages, setMessages] = useState<Record<string, string>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const inFlight = useRef(false)
  const alive = useRef(false)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])

  const draft = forms[section.id] ?? draftFromSectionState(initial)
  const isDirty = dirty[section.id] ?? false
  const version = versions[section.id] ?? initial.version
  const message = messages[section.id] ?? ''
  const error = errors[section.id] ?? ''
  const clinicianAuthored = !sectionUsesGeneration(section)
  const [sendStepActive, setSendStepActive] = useState(false)
  useEffect(() => { setSendStepActive(false) }, [section.id])
  const approvable = canApproveSection(draft, section.review_gate)
  const barPrimary = saveBarPrimaryAction({ dirty: isDirty, canApprove: approvable, sendStepActive })

  const updateDraft = useCallback((updater: (current: EditorDraft) => EditorDraft) => {
    setForms((current) => {
      const base = current[section.id] ?? draftFromSectionState(initial)
      const next = updater(base)
      return next === base ? current : { ...current, [section.id]: next }
    })
  }, [section.id, initial])
  const markDirty = useCallback((value: boolean) => {
    setDirty((current) => ({ ...current, [section.id]: value }))
  }, [section.id])

  // R6 (PT-09 / ADR 0018): when a correction returns this open APPROVED
  // section to needs_review on the server, the pill follows — but ONLY the
  // status. The saved/unsaved textarea text is never rewritten here.
  useEffect(() => {
    if (initial.status !== 'needs_review') return
    let flipped = false
    setForms((current) => {
      const base = current[section.id] ?? draftFromSectionState(initial)
      if (base.status !== 'approved') return current
      flipped = true
      return { ...current, [section.id]: { ...base, status: 'needs_review' } }
    })
    if (flipped) {
      setMessages((current) => ({
        ...current,
        [section.id]: 'A source correction returned this section to Needs review. Your unsaved text was not changed.',
      }))
    }
  }, [initial.status, initial.section_id, section.id])

  const generated = useCallback((text: string, claimIds: string[]) => {
    if (!alive.current) return
    // Defense in depth: even if a caller wires this callback, sections the
    // clinician writes never receive model text.
    setForms((current) => {
      const base = current[section.id] ?? draftFromSectionState(initial)
      const next = applyGeneratedText(section, base, text, claimIds)
      return next === base ? current : { ...current, [section.id]: next }
    })
    if (clinicianAuthored) return
    markDirty(true)
    setMessages((current) => ({ ...current, [section.id]: 'Generated draft is in the editor. Review it, then Save section.' }))
    setErrors((current) => ({ ...current, [section.id]: '' }))
  }, [clinicianAuthored, initial, markDirty, section])

  function changeText(text: string) {
    updateDraft((current) => editDraftText(current, text))
    markDirty(true)
  }
  function toggleClaim(id: string) {
    updateDraft((current) => toggleDraftClaim(current, id))
    markDirty(true)
  }
  async function saveSection(status?: EditorDraft['status']) {
    if (inFlight.current || busy) return
    const form = status ? { ...draft, status } : draft
    if (status) updateDraft((current) => setDraftStatus(current, status))
    inFlight.current = true; setSaving(true); onBusyChange(true)
    setErrors((current) => ({ ...current, [section.id]: '' }))
    setMessages((current) => ({ ...current, [section.id]: '' }))
    try {
      const saved = await jsonRequest<{ version: number }>(`${workspaceUrl(workspaceId)}/sections/${encodeURIComponent(section.id)}`, 'PUT', {
        template_id: template.template_id, template_version: template.version, text: form.text,
        claim_ids: form.claimIds, status: form.status, reviewer: form.reviewer.trim() || null,
      })
      if (!alive.current) return
      setVersions((current) => ({ ...current, [section.id]: saved.version }))
      markDirty(false)
      onSaved({ ...initial, text: form.text, status: form.status, reviewer: form.reviewer.trim() || null, claim_ids: form.claimIds, version: saved.version })
      setMessages((current) => ({ ...current, [section.id]: 'Section saved.' }))
    } catch { if (alive.current) setErrors((current) => ({ ...current, [section.id]: 'Could not save the section. Check required text and reviewer, then try again.' })) }
    finally { if (alive.current) { inFlight.current = false; setSaving(false); onBusyChange(false) } }
  }
  return <article className="section-canvas">
    <div className="canvas-meta"><span className={`status-pill ${draft.status}`}>{STATUS_LABELS[draft.status]}</span><span>v{version} · {template.template_id}</span></div>
    <h3>{section.title}</h3><p className="section-id">{section.id}</p>
    {clinicianAuthored && <section className="clinician-authored-notice" role="note" data-testid="clinician-authored-notice">
      <h4>You write this section</h4>
      <p>{CLINICIAN_AUTHORED_NOTICE}</p>
    </section>}
    <div className="editor-block"><label className="field-label" htmlFor="section-text">Section text</label><textarea id="section-text" className="editor-input" value={draft.text} disabled={busy} onChange={(event) => changeText(event.target.value)} rows={14} placeholder={clinicianAuthored ? 'Write this section yourself. It is never generated.' : 'Write this section. Approved sections must be non-empty.'} />
      {clinicianAuthored && draft.text.trim() === '' && <p className="you-write-this" data-testid="you-write-this">{CLINICIAN_AUTHORED_EMPTY}</p>}
    </div>
    <div className="editor-controls"><label className="field-label">Status<select className="select-input" disabled={busy} value={draft.status} onChange={(event) => { updateDraft((current) => setDraftStatus(current, event.target.value as SectionStatus)); markDirty(true) }}>{STATUS_ORDER.map((status) => <option key={status} value={status}>{STATUS_LABELS[status]}</option>)}</select></label>
      {section.review_gate === 'licensed_clinician' && <label className="field-label">Reviewer (required to approve)<input className="text-input" disabled={busy} value={draft.reviewer} onChange={(event) => { updateDraft((current) => ({ ...current, reviewer: event.target.value })); markDirty(true) }} /></label>}
    </div>
    <div className="claims-block"><p className="field-label">Source claims</p>
      {!claims.length ? <p className="muted">Upload a material and review intake claims to add sources.</p> : <ul className="claim-list">{claims.map((claim) => <ClaimRow key={claim.id} claim={claim} checked={draft.claimIds.includes(claim.id)} busy={busy} onToggle={toggleClaim} onOpenSource={onOpenSourceClaim} />)}</ul>}
    </div>
    {!clinicianAuthored && <EgressReviewPanel key={section.id} workspaceId={workspaceId} templateId={template.template_id} templateVersion={template.version} sectionId={section.id} sectionTitle={section.title} claimIds={draft.claimIds} sourceRevision={sourceRevision} onGenerated={generated} onBusyChange={onBusyChange} onPrimaryStepChange={setSendStepActive} disabled={busy} />}
    {error && <div className="error-banner" role="alert">{error}</div>}
    <div className="save-bar">
      <button type="button" className={barPrimary === 'approve' ? 'primary-button' : 'secondary-button'} disabled={busy || isDirty || !approvable} data-testid="approve-section" title={isDirty ? 'Save first' : undefined} onClick={() => void saveSection('approved')}>Approve section</button>
      <button type="button" className={barPrimary === 'save' ? 'primary-button' : 'secondary-button'} disabled={busy || !isDirty} aria-busy={saving} data-testid="save-section" onClick={() => void saveSection()}>{saving ? 'Saving…' : 'Save section'}</button>
      <span className={`saved-state${isDirty ? ' dirty' : ''}`} data-testid="save-state" role="status">{saveStateLabel(isDirty)}</span>
      {message && <span className="saved-flash" role="status">{message}</span>}
    </div>
    <div className={`review-gate${section.review_gate === 'licensed_clinician' ? ' clinical' : ''}`}><div><strong>{section.review_gate === 'licensed_clinician' ? 'Licensed clinician gate' : 'Standard review gate'}</strong><p>{section.review_gate === 'licensed_clinician' ? 'Section approval requires a reviewer name and non-empty text.' : 'Section approval requires non-empty text.'}</p></div></div>
  </article>
}
export default App
