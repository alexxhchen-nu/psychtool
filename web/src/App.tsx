import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { apiRequest, createCase, getWorkspace, jsonRequest, workspaceUrl } from './api'
import type { Claim, ClaimSuggestion, Material, ReportTemplate, SectionState, SectionStatus, TemplateSection, UploadResult, Workspace } from './types'
import { validateCaseId } from './case-form'
import MaterialUploadPanel from './components/MaterialUploadPanel'
import PasteMaterialPanel from './components/PasteMaterialPanel'
import EgressReviewPanel from './components/EgressReviewPanel'
import './App.css'

export const PRIVACY_BANNER = 'Please note: This prototype is not HIPAA compliant yet. Do not enter real patient information. Use only synthetic or separately approved practice materials.'

const STATUS_LABELS: Record<SectionStatus, string> = { empty: 'Empty', draft: 'Draft', needs_review: 'Needs review', approved: 'Approved' }
const STATUS_ORDER: SectionStatus[] = ['empty', 'draft', 'needs_review', 'approved']

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
    <div className="privacy-banner" role="note">{PRIVACY_BANNER}</div>
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
  const [error, setError] = useState('')
  const [ready, setReady] = useState(false)
  const [busy, setBusy] = useState(false)
  const [sourceRevision, setSourceRevision] = useState(0)
  const [syntheticConfirmed, setSyntheticConfirmed] = useState(false)
  const alive = useRef(false)
  const mutation = useRef(false)
  const base = workspaceUrl(workspaceId)
  const changeBusy = useCallback((value: boolean) => { mutation.current = value; setBusy(value); onBusyChange(value) }, [onBusyChange])

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
        <button className="ghost-button" disabled={busy || !ready} aria-expanded={showNames} onClick={() => setShowNames(!showNames)}>Identifying info</button>
      </div>
    </section>
    {error && <div className="error-banner" role="alert">{error}</div>}
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
    {ready && selected && selectedState && <div className="report-grid">
      <aside className="section-rail" aria-label="Report sections"><div className="rail-heading"><span>Document map</span><strong>{template.sections.length} sections</strong></div>
        <ol>{template.sections.map((section, index) => {
          const status = sections.find((state) => state.section_id === section.id)?.status ?? 'empty'
          return <li key={section.id}><button className={section.id === selectedId ? 'section-link active' : 'section-link'} disabled={busy} aria-current={section.id === selectedId ? 'step' : undefined} aria-label={`${section.title}, ${STATUS_LABELS[status]}`} onClick={() => setSelectedId(section.id)}>
            <span className="section-number">{String(index + 1).padStart(2, '0')}</span><span className="section-name">{section.title}</span><span className={`status-dot ${status}`} title={STATUS_LABELS[status]} />
          </button></li>
        })}</ol>
      </aside>
      <SectionEditor key={selected.id} workspaceId={workspaceId} template={template} section={selected} initial={selectedState} claims={claims} sourceRevision={sourceRevision} busy={busy} onBusyChange={changeBusy} onSaved={(state) => setSections((items) => items.map((item) => item.section_id === state.section_id ? state : item))} />
      <aside className="review-panel"><h3>{approved} of {template.sections.length} approved</h3><p>Model requests and report sections have separate approval steps. Generated text stays unsaved until you save it.</p>
        <div className="state-key">{STATUS_ORDER.map((status) => <div key={status}><span className={`status-dot ${status}`} />{STATUS_LABELS[status]}</div>)}</div>
        <small>Development workspace for synthetic or public materials. Reviewer names are labels, not verified identities. These controls do not establish HIPAA compliance.</small>
      </aside>
    </div>}
  </>
}

interface EditorProps extends WorkbenchProps {
  section: TemplateSection
  initial: SectionState
  claims: Claim[]
  sourceRevision: number
  busy: boolean
  onSaved: (state: SectionState) => void
}
function SectionEditor({ workspaceId, template, section, initial, claims, sourceRevision, busy, onBusyChange, onSaved }: EditorProps) {
  const [form, setForm] = useState(() => ({ text: initial.text, status: initial.status, reviewer: initial.reviewer ?? '', claimIds: initial.claim_ids }))
  const [version, setVersion] = useState(initial.version)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const inFlight = useRef(false)
  const alive = useRef(false)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const generated = useCallback((text: string, claimIds: string[]) => {
    if (!alive.current) return
    setForm((current) => ({ ...current, text, claimIds, status: 'draft', reviewer: '' }))
    setMessage('Generated draft is in the editor. Review it, then Save section.'); setError('')
  }, [])
  function changeText(text: string) {
    setForm((current) => ({ ...current, text, status: current.status === 'approved' ? 'draft' : current.status, reviewer: current.status === 'approved' ? '' : current.reviewer }))
    setMessage('Unsaved changes')
  }
  function toggleClaim(id: string) {
    setForm((current) => ({ ...current, claimIds: current.claimIds.includes(id) ? current.claimIds.filter((value) => value !== id) : [...current.claimIds, id], status: current.status === 'approved' ? 'draft' : current.status }))
    setMessage('Unsaved changes')
  }
  async function saveSection() {
    if (inFlight.current || busy) return
    inFlight.current = true; setSaving(true); onBusyChange(true); setError(''); setMessage('')
    try {
      const saved = await jsonRequest<{ version: number }>(`${workspaceUrl(workspaceId)}/sections/${encodeURIComponent(section.id)}`, 'PUT', {
        template_id: template.template_id, template_version: template.version, text: form.text,
        claim_ids: form.claimIds, status: form.status, reviewer: form.reviewer.trim() || null,
      })
      if (!alive.current) return
      setVersion(saved.version)
      onSaved({ ...initial, text: form.text, status: form.status, reviewer: form.reviewer.trim() || null, claim_ids: form.claimIds, version: saved.version })
      setMessage('Section saved.')
    } catch { if (alive.current) setError('Could not save the section. Check required text and reviewer, then try again.') }
    finally { if (alive.current) { inFlight.current = false; setSaving(false); onBusyChange(false) } }
  }
  return <article className="section-canvas">
    <div className="canvas-meta"><span className={`status-pill ${form.status}`}>{STATUS_LABELS[form.status]}</span><span>v{version} · {template.template_id}</span></div>
    <h3>{section.title}</h3><p className="section-id">{section.id}</p>
    <div className="editor-block"><label className="field-label" htmlFor="section-text">Section text</label><textarea id="section-text" className="editor-input" value={form.text} disabled={busy} onChange={(event) => changeText(event.target.value)} rows={14} placeholder="Write this section. Approved sections must be non-empty." /></div>
    <div className="editor-controls"><label className="field-label">Status<select className="select-input" disabled={busy} value={form.status} onChange={(event) => { setForm((current) => ({ ...current, status: event.target.value as SectionStatus })); setMessage('Unsaved changes') }}>{STATUS_ORDER.map((status) => <option key={status} value={status}>{STATUS_LABELS[status]}</option>)}</select></label>
      {section.review_gate === 'licensed_clinician' && <label className="field-label">Reviewer (required to approve)<input className="text-input" disabled={busy} value={form.reviewer} onChange={(event) => setForm((current) => ({ ...current, reviewer: event.target.value }))} /></label>}
    </div>
    <div className="claims-block"><p className="field-label">Source claims</p>
      {!claims.length ? <p className="muted">Upload a material and review intake claims to add sources.</p> : <ul className="claim-list">{claims.map((claim) => <li key={claim.id}><label className="claim-row"><input type="checkbox" disabled={busy} checked={form.claimIds.includes(claim.id)} onChange={() => toggleClaim(claim.id)} /><span className="claim-id">{claim.id}</span><span className="claim-text">{claim.text}</span></label></li>)}</ul>}
    </div>
    <EgressReviewPanel workspaceId={workspaceId} templateId={template.template_id} templateVersion={template.version} sectionId={section.id} sectionTitle={section.title} claimIds={form.claimIds} sourceRevision={sourceRevision} onGenerated={generated} onBusyChange={onBusyChange} disabled={busy} />
    {error && <div className="error-banner" role="alert">{error}</div>}
    <div className="save-bar"><button className="primary-button" disabled={busy} aria-busy={saving} onClick={saveSection}>{saving ? 'Saving…' : 'Save section'}</button><span className="saved-flash" role="status">{message}</span></div>
    <div className={`review-gate${section.review_gate === 'licensed_clinician' ? ' clinical' : ''}`}><div><strong>{section.review_gate === 'licensed_clinician' ? 'Licensed clinician gate' : 'Standard review gate'}</strong><p>{section.review_gate === 'licensed_clinician' ? 'Section approval requires a reviewer name and non-empty text.' : 'Section approval requires non-empty text.'}</p></div></div>
  </article>
}
export default App
