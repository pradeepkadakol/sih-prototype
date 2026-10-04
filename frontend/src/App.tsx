import { useCallback, useEffect, useRef, useState } from 'react'
import { api, title } from './api'
import type { Case, CaseDetail, Site, Summary, User } from './types'
import Reviewer from './Reviewer'
import Inspector from './Inspector'

type Page = 'overview' | 'cases' | 'review' | 'activity'

export default function App() {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('verisight_token'))
  const [user, setUser] = useState<User | null>(null)
  const [initializing, setInitializing] = useState(true)
  const [page, setPage] = useState<Page>('overview')
  const [cases, setCases] = useState<Case[]>([])
  const [detail, setDetail] = useState<CaseDetail | null>(null)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [sites, setSites] = useState<Site[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const selectedIdRef = useRef<number | null>(null)

  const refresh = useCallback(async (selectedId?: number | null, role?: string) => {
    if (!token) return
    const currentRole = role || user?.role
    setLoading(true)
    try {
      const [caseRows, siteRows] = await Promise.all([api<Case[]>('/inspections', token), api<Site[]>('/sites', token)])
      setCases(caseRows)
      setSites(siteRows)
      if (currentRole === 'reviewer') setSummary(await api<Summary>('/dashboard/summary', token))
      const id = selectedId === undefined ? selectedIdRef.current : selectedId
      selectedIdRef.current = id || null
      if (id) setDetail(await api<CaseDetail>(`/inspections/${id}`, token))
      else setDetail(null)
      setError('')
    } catch (cause) { setError((cause as Error).message) }
    finally { setLoading(false) }
  }, [token, user?.role])

  useEffect(() => {
    if (!token) { setInitializing(false); return }
    api<User>('/me', token).then(identity => { setUser(identity); setInitializing(false) })
      .catch(() => { localStorage.removeItem('verisight_token'); setToken(null); setInitializing(false) })
  }, [token])

  useEffect(() => { if (user && token) void refresh(null, user.role) }, [user, token, refresh])

  async function login(username: string, password: string) {
    setError('')
    setLoading(true)
    try {
      const result = await api<{ token: string; user: User }>('/login', null, 'POST', { username, password })
      localStorage.setItem('verisight_token', result.token)
      setToken(result.token)
      setUser(result.user)
      setPage('overview')
    } catch (cause) { setError((cause as Error).message) }
    finally { setLoading(false) }
  }

  function logout() {
    localStorage.removeItem('verisight_token')
    selectedIdRef.current = null
    setToken(null); setUser(null); setCases([]); setDetail(null); setSummary(null); setError(''); setNotice('')
  }

  async function openCase(id: number) {
    if (!token) return
    setLoading(true); setError('')
    try { setDetail(await api<CaseDetail>(`/inspections/${id}`, token)); selectedIdRef.current = id; setPage('cases') }
    catch (cause) { setError((cause as Error).message) }
    finally { setLoading(false) }
  }

  async function perform<T>(path: string, method: string, body?: unknown, message?: string, selectedId?: number | null): Promise<T | undefined> {
    if (!token) return
    setLoading(true); setError(''); setNotice('')
    try {
      const result = await api<T>(path, token, method, body)
      await refresh(selectedId)
      if (message) setNotice(message)
      return result
    } catch (cause) { setError((cause as Error).message) }
    finally { setLoading(false) }
  }

  if (initializing) return <div className="full-loader">Loading VeriSight demo…</div>
  if (!user || !token) return <Login onLogin={login} loading={loading} error={error} />

  const nav: { key: Page; label: string; glyph: string }[] = user.role === 'reviewer'
    ? [{ key: 'overview', label: 'Overview', glyph: '▦' }, { key: 'cases', label: 'Inspection cases', glyph: '▤' }, { key: 'review', label: 'Review queue', glyph: '◎' }, { key: 'activity', label: 'Audit trail', glyph: '◷' }]
    : [{ key: 'overview', label: 'My assignments', glyph: '▦' }, { key: 'cases', label: 'Inspection workspace', glyph: '▤' }]
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">V<span>✓</span></div><div><strong>VeriSight</strong><small>INSPECTION OPERATIONS</small></div></div>
      <div className="sidebar-label">WORKSPACE</div>
      <nav aria-label="Main navigation">{nav.map(item => <button key={item.key} className={`nav-button ${page === item.key ? 'active' : ''}`} onClick={() => { setPage(item.key); if (item.key === 'overview') { setDetail(null); selectedIdRef.current = null } }}><span className="nav-glyph">{item.glyph}</span>{item.label}</button>)}</nav>
      <div className="sidebar-spacer" />
      <div className="sidebar-note"><span className="small-pulse" /> DEMO MODE <p>Fictional Nila District data. Simulated integrations are labelled.</p></div>
      <div className="account"><div className="avatar">{user.display_name[0]}</div><div><strong>{user.display_name}</strong><small>{title(user.role)}</small></div><button title="Sign out" aria-label="Sign out" onClick={logout}>↗</button></div>
    </aside>
    <div className="main-area">
      <header className="topbar"><div className="mobile-brand">VeriSight</div><div className="crumb">NILA DISTRICT <span>/</span> {nav.find(item => item.key === page)?.label.toUpperCase()}</div><div className="topbar-right"><span className="live-dot" /> Local demo <span className="divider" /> SIH26095</div></header>
      <main className="content">
        <div className="global-banner"><strong>Prototype notice</strong><span>This is fictional demo data. VeriSight is not production-ready and needs security, privacy, legal, and operational review before real deployment.</span></div>
        {error && <div className="alert error" role="alert"><span>{error}</span><button onClick={() => setError('')}>Dismiss</button></div>}
        {notice && <div className="alert success" role="status"><span>{notice}</span><button onClick={() => setNotice('')}>Dismiss</button></div>}
        {loading && <div className="loading-line" role="status">Updating records…</div>}
        {user.role === 'reviewer'
          ? <Reviewer page={page} cases={cases} detail={detail} summary={summary} sites={sites} openCase={openCase} perform={perform} refresh={() => refresh(detail?.id)} token={token} navigate={setPage} />
          : <Inspector page={page} cases={cases} detail={detail} openCase={openCase} perform={perform} userId={user.id} refresh={() => refresh(detail?.id)} />}
      </main>
      <nav className="mobile-nav" aria-label="Mobile navigation">{nav.map(item => <button key={item.key} className={page === item.key ? 'active' : ''} onClick={() => { setPage(item.key); if (item.key === 'overview') { setDetail(null); selectedIdRef.current = null } }}><span>{item.glyph}</span>{item.label}</button>)}</nav>
    </div>
  </div>
}

function Login({ onLogin, loading, error }: { onLogin: (username: string, password: string) => Promise<void>; loading: boolean; error: string }) {
  const [username, setUsername] = useState('reviewer')
  const [password, setPassword] = useState('')
  return <div className="login-page"><div className="login-left"><div className="login-brand"><div className="brand-mark">V<span>✓</span></div> VeriSight</div><div className="login-hero"><div className="eyebrow light">SMART INDIA HACKATHON · SIH26095</div><h1>Every inspection.<br /><em>Accountable.</em></h1><p>A clear view from assignment to action, built for a transparent local demonstration.</p><div className="hero-rule" /><div className="hero-features"><span>01 · Verifiable assignment</span><span>02 · Evidence integrity</span><span>03 · Actionable oversight</span></div></div><div className="login-foot">Fictional Nila District · Demo prototype</div></div><div className="login-right"><div className="login-card"><div className="eyebrow">SECURE WORKSPACE · DEMO MODE</div><h2>Welcome back</h2><p>Choose a seeded account to explore the reviewer or inspector workflow.</p>{error && <div className="alert error" role="alert">{error}</div>}<form onSubmit={event => { event.preventDefault(); void onLogin(username, password) }}><label>Demo account<select value={username} onChange={event => setUsername(event.target.value)}><option value="reviewer">Review Officer</option><option value="inspector.arya">Inspector · Arya</option><option value="inspector.kiran">Inspector · Kiran</option><option value="inspector.meera">Inspector · Meera</option></select></label><label>Password<input value={password} onChange={event => setPassword(event.target.value)} type="password" autoComplete="current-password" required /></label><button className="primary wide" type="submit" disabled={loading}>{loading ? 'Signing in…' : 'Enter workspace'} <span>→</span></button></form><div className="demo-credential">Demo credentials are documented in the repository README.</div></div><p className="login-disclaimer">Local prototype only. No real agencies, inspections, or live integrations.</p></div></div>
}
