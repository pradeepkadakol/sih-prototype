import { useEffect, useMemo, useState } from 'react'
import { niceDate, title } from './api'
import type { Case, CaseDetail, Finding } from './types'

type Perform = <T>(path: string, method: string, body?: unknown, message?: string, selectedId?: number | null) => Promise<T | undefined>
type Answer = { item_key: string; answer: string; note: string }
type Props = { page: string; cases: Case[]; detail: CaseDetail | null; openCase: (id: number) => Promise<void>; perform: Perform; userId: number; refresh: () => Promise<void> }

export default function Inspector({ page, cases, detail, openCase, perform, userId, refresh }: Props) {
  const active = cases.filter(item => item.status !== 'completed')
  return <><div className="page-heading"><div><div className="eyebrow">FIELD OPERATIONS · DEMO MODE</div><h1>{page === 'overview' ? 'My assignments' : 'Inspection workspace'}</h1><p>Inspect the site, record observations, and submit a clear field report.</p></div><div className="field-summary">{active.length} active assignment{active.length === 1 ? '' : 's'}</div></div>
    <div className="inspector-layout"><div className="inspector-case-list">{cases.length ? cases.map(item => <button key={item.id} onClick={() => void openCase(item.id)} className={`field-card ${detail?.id === item.id ? 'selected' : ''}`}><div className="field-card-top"><span>{item.code}</span><span className={`badge ${item.status}`}>{title(item.status)}</span></div><h3>{item.site.name}</h3><p>{item.site.organization} · {item.site.region}</p><div className="field-card-foot"><span className={`risk ${item.site.risk}`}>{title(item.site.risk)} risk</span><span>Open case →</span></div></button>) : <div className="empty-state">No inspections are assigned to this demo account. Sign in as another seeded inspector or ask the reviewer to assign a case.</div>}</div><div>{detail ? <InspectionWorkspace key={detail.id} detail={detail} perform={perform} userId={userId} refresh={refresh} /> : <div className="panel select-case"><div className="select-icon">⌖</div><h3>Select an assignment</h3><p>Open a case to check in, answer the checklist, add findings and evidence, then review your report.</p></div>}</div></div>
  </>
}

function InspectionWorkspace({ detail, perform, userId, refresh }: { detail: CaseDetail; perform: Perform; userId: number; refresh: () => Promise<void> }) {
  const draftKey = `verisight_draft_${userId}_${detail.id}`
  const [answers, setAnswers] = useState<Answer[]>(() => {
    try { return JSON.parse(localStorage.getItem(draftKey) || 'null') || detail.responses.map(row => ({ item_key: row.item_key, answer: row.answer, note: row.note })) }
    catch { return detail.responses.map(row => ({ item_key: row.item_key, answer: row.answer, note: row.note })) }
  })
  const [pending, setPending] = useState(() => Boolean(localStorage.getItem(draftKey)))
  const [locationNote, setLocationNote] = useState('')
  const [finding, setFinding] = useState({ severity: 'medium', category: 'Safety', description: '', recommended_action: '' })
  const [reviewOpen, setReviewOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const missing = useMemo(() => detail.template.filter(item => item.required && !['pass', 'fail', 'na'].includes(answers.find(row => row.item_key === item.key)?.answer || '')), [detail.template, answers])
  const answeredCount = detail.template.filter(item => ['pass', 'fail', 'na'].includes(answers.find(row => row.item_key === item.key)?.answer || '')).length

  function changeAnswer(key: string, patch: Partial<Answer>) {
    const next = [...answers]
    const index = next.findIndex(row => row.item_key === key)
    if (index < 0) next.push({ item_key: key, answer: '', note: '', ...patch })
    else next[index] = { ...next[index], ...patch }
    setAnswers(next)
    localStorage.setItem(draftKey, JSON.stringify(next))
    setPending(true)
  }

  async function syncDraft() {
    if (!detail.inspection || detail.status !== 'in_progress' || !answers.length) return
    setSyncing(true)
    const result = await perform(`/inspections/${detail.id}/checklist`, 'PUT', { responses: answers.filter(row => row.answer) }, 'Checklist synced to server.', detail.id)
    if (result) { localStorage.removeItem(draftKey); setPending(false) }
    setSyncing(false)
  }

  useEffect(() => {
    function onOnline() { if (pending && detail.status === 'in_progress') void syncDraft() }
    window.addEventListener('online', onOnline)
    return () => window.removeEventListener('online', onOnline)
  })

  async function checkin(override = false) {
    if (override) { await perform(`/inspections/${detail.id}/check-in`, 'POST', { demo_override: true }, 'Demo override check-in recorded.', detail.id); return }
    if (!navigator.geolocation) { setLocationNote('Geolocation is unavailable in this browser. A seeded case may use the clearly labelled demo override.'); return }
    setLocationNote('Requesting browser location…')
    navigator.geolocation.getCurrentPosition(async position => {
      const result = await perform(`/inspections/${detail.id}/check-in`, 'POST', { latitude: position.coords.latitude, longitude: position.coords.longitude, accuracy_m: position.coords.accuracy }, 'Check-in recorded.', detail.id)
      setLocationNote(result ? `Browser reported accuracy ${Math.round(position.coords.accuracy)} m. This is an untrusted client signal.` : 'Location could not be accepted within the site geofence. If this is a seeded case, use the demo override.')
    }, () => setLocationNote('Location permission was denied or timed out. Seeded demo cases can use a clearly labelled override.'), { enableHighAccuracy: true, timeout: 10000 })
  }

  async function addFinding(event: React.FormEvent) {
    event.preventDefault()
    const result = await perform<Finding>(`/inspections/${detail.id}/findings`, 'POST', finding, 'Finding recorded.', detail.id)
    if (result) setFinding({ severity: 'medium', category: 'Safety', description: '', recommended_action: '' })
  }

  async function upload(file: File) {
    if (file.size > 5_000_000) { setLocationNote('Evidence must be 5 MB or smaller.'); return }
    setUploading(true)
    try {
      const data = await new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = () => reject(new Error('File could not be read')); reader.readAsDataURL(file) })
      await perform(`/inspections/${detail.id}/evidence`, 'POST', { filename: file.name, mime_type: file.type, data_base64: data, client_capture_time: file.lastModified ? new Date(file.lastModified).toISOString() : null }, 'Evidence stored with server SHA-256 hash.', detail.id)
    } catch { setLocationNote('File could not be read. Please try another image.') }
    finally { setUploading(false) }
  }

  async function sampleEvidence() {
    const canvas = document.createElement('canvas'); canvas.width = 1000; canvas.height = 620
    const ctx = canvas.getContext('2d'); if (!ctx) return
    ctx.fillStyle = '#d9e8e4'; ctx.fillRect(0, 0, 1000, 620)
    ctx.fillStyle = '#0c3942'; ctx.fillRect(0, 0, 1000, 150)
    ctx.fillStyle = '#fff'; ctx.font = 'bold 42px sans-serif'; ctx.fillText('SAMPLE DEMO EVIDENCE', 52, 94)
    ctx.fillStyle = '#a7c7be'; ctx.fillRect(90, 285, 820, 200)
    ctx.fillStyle = '#48766d'; ctx.fillRect(150, 225, 200, 260); ctx.fillRect(395, 255, 160, 230); ctx.fillRect(610, 195, 230, 290)
    ctx.fillStyle = '#fff'; ctx.font = '26px sans-serif'; ctx.fillText(detail.site.name, 52, 555)
    canvas.toBlob(blob => { if (blob) void upload(new File([blob], 'verisight-sample.png', { type: 'image/png' })) }, 'image/png')
  }

  async function submit() {
    if (missing.length || pending) return
    const result = await perform(`/inspections/${detail.id}/submit`, 'POST', {}, 'Inspection submitted for reviewer oversight.', detail.id)
    if (result) setReviewOpen(false)
  }

  return <section className="panel inspection-panel"><div className="detail-top"><div><div className="eyebrow">{detail.code} · FIELD REPORT</div><h2>{detail.site.name}</h2><p>{detail.site.organization} · {detail.site.region}</p></div><span className={`badge ${detail.status}`}>{title(detail.status)}</span></div><div className="field-meta"><span><b>{title(detail.site.risk)} risk</b></span><span>Site {detail.site.code}</span><span>{detail.site.latitude.toFixed(4)}, {detail.site.longitude.toFixed(4)}</span></div>
    {detail.status === 'assigned' && <div className="workflow-step"><div className="step-number">01</div><div><h3>Start inspection / Check in</h3><p>Browser location is compared with the site’s configured geofence. Client location and timestamps are untrusted signals.</p><div className="button-row"><button className="primary" onClick={() => void checkin()}>⌖ Use current location</button>{detail.seeded && <button className="secondary" onClick={() => void checkin(true)}>Use demo override</button>}</div>{locationNote && <div className="inline-warning" role="status">{locationNote}</div>}</div></div>}
    {detail.inspection && <div className="checkin-summary"><span className="check-icon">✓</span><div><strong>Checked in · {title(detail.inspection.geofence_result)}</strong><small>{niceDate(detail.inspection.checkin_at)} · {detail.inspection.distance_m == null ? 'No client location reported' : `${Math.round(detail.inspection.distance_m)} m from site`}</small></div></div>}
    <div className="workflow-step"><div className="step-number">02</div><div className="step-content"><h3>Site checklist</h3><p>Required items must be answered before submission.</p>{detail.template.map(item => { const answer = answers.find(row => row.item_key === item.key); return <div className="checklist-item" key={item.key}><div className="checklist-head"><strong>{item.label}</strong>{item.required && <small>REQUIRED</small>}</div><div className="answer-options" role="group" aria-label={item.label}>{[['pass', 'Pass'], ['fail', 'Fail'], ['na', 'Not applicable']].map(([value, label]) => <button type="button" key={value} className={answer?.answer === value ? 'selected' : ''} onClick={() => changeAnswer(item.key, { answer: value })} disabled={detail.status === 'completed'} aria-pressed={answer?.answer === value}>{label}</button>)}</div><label className="note-label">Observation note (optional)<input value={answer?.note || ''} onChange={event => changeAnswer(item.key, { note: event.target.value })} placeholder="Add context for the reviewer" disabled={detail.status === 'completed'} /></label></div> })}{detail.status === 'in_progress' && <><div className={pending ? 'draft-state pending' : 'draft-state synced'}>{pending ? '● Saved on this device — not submitted' : '✓ Checklist synced to server'}</div><button className="secondary" onClick={() => void syncDraft()} disabled={!pending || syncing}>{syncing ? 'Syncing…' : 'Sync checklist now'}</button></>}{detail.status === 'assigned' && <div className="form-note">You can draft responses now. Start the inspection to sync them to the server.</div>}</div></div>
    <div className="workflow-step"><div className="step-number">03</div><div className="step-content"><h3>Findings & evidence</h3><p>Describe the issue and attach an image when useful.</p>{detail.findings.map(row => <div className="field-finding" key={row.id}><span className={`severity ${row.severity}`}>{title(row.severity)}</span><div><strong>{row.category}</strong><p>{row.description}</p><small>Review: {title(row.review_status)}</small></div></div>)}{detail.status === 'in_progress' && <form className="finding-form" onSubmit={event => void addFinding(event)}><div className="form-row"><label>Severity<select value={finding.severity} onChange={event => setFinding({ ...finding, severity: event.target.value })}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></label><label>Category<input value={finding.category} onChange={event => setFinding({ ...finding, category: event.target.value })} minLength={2} required /></label></div><label>Finding description<textarea value={finding.description} onChange={event => setFinding({ ...finding, description: event.target.value })} placeholder="What did you observe?" minLength={5} required /></label><label>Recommended action<input value={finding.recommended_action} onChange={event => setFinding({ ...finding, recommended_action: event.target.value })} placeholder="What should happen next?" minLength={3} required /></label><button className="secondary">＋ Add finding</button></form>}
      <div className="evidence-list">{detail.evidence.map(row => <div key={row.id} className="field-evidence"><strong>{row.original_filename}</strong><small>Stored {niceDate(row.server_received_at)} · SHA-256 {row.sha256.slice(0, 14)}…</small></div>)}</div>{detail.status === 'in_progress' && <div className="button-row upload-actions"><label className="secondary upload-label">↑ Upload image<input type="file" accept="image/png,image/jpeg,image/webp" onChange={event => { const file = event.target.files?.[0]; if (file) void upload(file); event.target.value = '' }} /></label><button className="secondary" onClick={() => void sampleEvidence()} disabled={uploading}>{uploading ? 'Uploading…' : 'Use built-in sample image'}</button></div>}<div className="form-note">Allowed: PNG, JPEG, WebP; max 5 MB. The server hashes received bytes. A hash cannot prove where or when a photo was taken.</div></div></div>
    <div className="workflow-step last"><div className="step-number">04</div><div className="step-content"><h3>Final review & submit</h3><p>Check your answers, findings, and evidence before submission.</p><button className="primary" onClick={() => setReviewOpen(value => !value)}>{reviewOpen ? 'Hide final review' : 'Open final review'}</button>{reviewOpen && <div className="final-review"><div><strong>Checklist</strong><span>{answeredCount} of {detail.template.length} items answered</span></div><div><strong>Findings</strong><span>{detail.findings.length} recorded</span></div><div><strong>Evidence</strong><span>{detail.evidence.length} stored</span></div>{missing.length > 0 && <div className="inline-warning">Answer required items: {missing.map(item => item.label).join(', ')}.</div>}{pending && <div className="inline-warning">Sync the local checklist draft before submitting.</div>}{detail.status === 'completed' ? <div className="submit-done">✓ Submitted {niceDate(detail.completed_at)}</div> : <button className="primary wide" onClick={() => void submit()} disabled={detail.status !== 'in_progress' || missing.length > 0 || pending}>Submit inspection →</button>}</div>}</div></div>
    <button className="text-button refresh-detail" onClick={() => void refresh()}>↻ Refresh server record</button>
  </section>
}
