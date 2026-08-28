import { useState } from 'react'
import './Sidebar.css'

const PROTOCOL_META = {
  auto:       { icon: '◇', label: 'Auto',       color: '#22d3ee' },
  council:    { icon: '⚖', label: 'Council',    color: '#5b8af5' },
  debate:     { icon: '⚔', label: 'Debate',     color: '#f87171' },
  redteam:    { icon: '🔴', label: 'Red Team',   color: '#fb923c' },
  consensus:  { icon: '🤝', label: 'Consensus',  color: '#4ade80' },
  specialist: { icon: '🎯', label: 'Specialist', color: '#a78bfa' },
  tournament: { icon: '🏆', label: 'Tournament', color: '#fbbf24' },
}

function timeAgo(iso) {
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1)  return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

export default function Sidebar({ sessions, activeId, onSelect, onNewChat }) {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <aside className={`sidebar ${collapsed ? 'sidebar--collapsed' : ''}`}>
      <div className="sidebar-header">
        {!collapsed && (
          <div className="sidebar-brand">
            <span className="brand-icon">⚡</span>
            <span className="brand-name">Weiping Council</span>
          </div>
        )}
        <button
          className="icon-btn"
          onClick={() => setCollapsed(c => !c)}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? '›' : '‹'}
        </button>
      </div>

      {!collapsed && (
        <>
          <button className="new-chat-btn" onClick={onNewChat}>
            <span>＋</span> New Query
          </button>

          <div className="sidebar-section-label">Recent</div>

          <nav className="session-list">
            {sessions.length === 0 && (
              <div className="session-empty">No sessions yet</div>
            )}
            {sessions.map(s => {
              const meta = PROTOCOL_META[s.protocol] || PROTOCOL_META.council
              return (
                <button
                  key={s.id}
                  className={`session-item ${s.id === activeId ? 'session-item--active' : ''}`}
                  onClick={() => onSelect(s.id)}
                >
                  <span className="session-proto-dot" style={{ background: meta.color }} />
                  <div className="session-info">
                    <div className="session-query">{s.query}</div>
                    <div className="session-meta">
                      <span style={{ color: meta.color }}>{meta.icon} {meta.label}</span>
                      <span className="session-time">{timeAgo(s.created_at)}</span>
                    </div>
                  </div>
                </button>
              )
            })}
          </nav>
        </>
      )}
    </aside>
  )
}
