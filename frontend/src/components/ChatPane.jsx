import { useState, useRef, useEffect } from 'react'
import { submitQuery } from '../api.js'
import ResultView from './ResultView.jsx'
import './ChatPane.css'

const PROTOCOLS = [
  { id: 'auto',       icon: '◇', label: 'Auto',       desc: 'Route by complexity with inspectable evidence' },
  { id: 'council',    icon: '⚖', label: 'Council',    desc: 'All models → peer review → synthesis' },
  { id: 'debate',     icon: '⚔', label: 'Debate',     desc: 'Pro vs con → rebuttals → verdict' },
  { id: 'redteam',    icon: '🔴', label: 'Red Team',   desc: 'Defend → attack → improve' },
  { id: 'consensus',  icon: '🤝', label: 'Consensus',  desc: 'Iterate until agreement' },
  { id: 'specialist', icon: '🎯', label: 'Specialist', desc: 'Route to domain expert' },
  { id: 'tournament', icon: '🏆', label: 'Tournament', desc: 'Bracket elimination' },
]

function RuntimeStatus({ health }) {
  if (!health) return <span className="runtime-pill runtime-pill--checking">checking</span>
  if (health.demo) {
    return (
      <div className="runtime-pill runtime-pill--demo" title="Started with --demo: replies are canned and no model is called">
        <span className="runtime-dot" />
        <span>demo</span>
        <span className="runtime-meta">canned replies</span>
      </div>
    )
  }
  const providers = health.providers || []
  const ready = providers.filter(p => p.ready).length
  const total = providers.length
  const label = health.status === 'ok' ? 'ready' : 'degraded'
  return (
    <div className={`runtime-pill runtime-pill--${label}`}>
      <span className="runtime-dot" />
      <span>{label}</span>
      <span className="runtime-meta">{ready}/{total} providers</span>
      <span className="runtime-meta">memory {health.agentmemory?.ready ? 'on' : 'off'}</span>
    </div>
  )
}

export default function ChatPane({ session, onResult, serverHealth }) {
  const [query, setQuery]       = useState('')
  const [protocol, setProtocol] = useState('council')
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)
  const [elapsed, setElapsed]   = useState(0)
  const textareaRef = useRef(null)
  const timerRef    = useRef(null)
  const abortRef    = useRef(null)

  // Stop the browser wait if this view unmounts. This does not claim that an
  // already-dispatched provider run was cancelled on the server.
  useEffect(() => () => abortRef.current?.abort(), [])

  // In demo mode, offer the sample question the canned replies were written for.
  const demoQuestion = serverHealth?.demo?.question
  useEffect(() => {
    if (demoQuestion) setQuery(q => q || demoQuestion)
  }, [demoQuestion])

  // Auto-resize textarea
  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px'
  }, [query])

  // Elapsed timer while loading
  useEffect(() => {
    if (loading) {
      setElapsed(0)
      timerRef.current = setInterval(() => setElapsed(e => e + 1), 1000)
    } else {
      clearInterval(timerRef.current)
    }
    return () => clearInterval(timerRef.current)
  }, [loading])

  const handleSubmit = async () => {
    const q = query.trim()
    if (!q || loading) return
    setError(null)
    setLoading(true)
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const result = await submitQuery(q, protocol, null, { signal: controller.signal })
      onResult(result)
      setQuery('')
    } catch (e) {
      setError(
        e.name === 'AbortError'
          ? 'Stopped waiting in this browser; server work may still finish and be saved.'
          : e.message,
      )
    } finally {
      abortRef.current = null
      setLoading(false)
    }
  }

  const handleStopWaiting = () => abortRef.current?.abort()

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const proto = PROTOCOLS.find(p => p.id === protocol)

  return (
    <div className="chat-pane">
      {/* Header */}
      <div className="chat-header">
        <div className="chat-header-left">
          <span className="chat-title">WEIPING_COUNCIL</span>
          <span className="chat-subtitle">Multi-LLM Deliberation</span>
        </div>
        <RuntimeStatus health={serverHealth} />
        {session && (
          <div className="chat-session-id">
            <span className="label">session</span>
            <code>{session.id?.slice(0, 8)}</code>
          </div>
        )}
      </div>

      {/* Result area */}
      <div className="chat-body">
        {!session && !loading && (
          <div className="chat-empty">
            <div className="empty-icon">⚡</div>
            <div className="empty-title">Weiping Council</div>
            <div className="empty-sub">Several models answer, review each other anonymously, and a chairman writes the final answer.</div>
            <div className="empty-protocols">
              {PROTOCOLS.map(p => (
                <button
                  key={p.id}
                  className={`proto-chip ${protocol === p.id ? 'proto-chip--active' : ''}`}
                  onClick={() => setProtocol(p.id)}
                >
                  {p.icon} {p.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {loading && (
          <div className="chat-loading">
            <div className="loading-spinner" />
            <div className="loading-text">
              <span className="loading-proto">{proto.icon} {proto.label}</span>
              <span className="loading-elapsed">{elapsed}s</span>
            </div>
            <div className="loading-sub">Running deliberation protocol…</div>
          </div>
        )}

        {session && !loading && <ResultView session={session} />}
      </div>

      {/* Error */}
      {error && (
        <div className="chat-error">
          <span>⚠ {error}</span>
          <button onClick={() => setError(null)}>✕</button>
        </div>
      )}

      {/* Input area */}
      <div className="chat-input-area">
        {/* Protocol selector */}
        <div className="proto-selector">
          {PROTOCOLS.map(p => (
            <button
              key={p.id}
              className={`proto-btn ${protocol === p.id ? 'proto-btn--active' : ''}`}
              onClick={() => setProtocol(p.id)}
              title={p.desc}
              disabled={loading}
            >
              <span className="proto-btn-icon">{p.icon}</span>
              <span className="proto-btn-label">{p.label}</span>
            </button>
          ))}
        </div>

        {/* Textarea + send */}
        <div className="input-row">
          <textarea
            ref={textareaRef}
            className="chat-textarea"
            placeholder={`Ask a question (${proto.label} protocol; Enter to send, Shift+Enter for newline)`}
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={loading}
            rows={1}
          />
          <button
            className="send-btn"
            onClick={loading ? handleStopWaiting : handleSubmit}
            disabled={!loading && !query.trim()}
            title={loading ? 'Stop waiting for response' : 'Send (Enter)'}
            aria-label={loading ? 'Stop waiting for response' : 'Send query'}
          >
            {loading ? '×' : '↑'}
          </button>
        </div>
      </div>
    </div>
  )
}
