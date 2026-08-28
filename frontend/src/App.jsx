import { useState, useEffect, useCallback } from 'react'
import Sidebar from './components/Sidebar.jsx'
import ChatPane from './components/ChatPane.jsx'
import { listSessions, getSession, healthCheck } from './api.js'
import './App.css'

export default function App() {
  const [sessions, setSessions]       = useState([])
  const [activeSession, setActive]    = useState(null)  // full session object
  const [serverOk, setServerOk]       = useState(null)  // null=checking, true, false
  const [serverHealth, setServerHealth] = useState(null)

  const refreshHealth = useCallback(() => {
    return healthCheck()
      .then((health) => {
        setServerHealth(health)
        setServerOk(true)
        return health
      })
      .catch(() => {
        setServerHealth(null)
        setServerOk(false)
      })
  }, [])

  // Health check on mount and periodically so readiness evidence does not go stale.
  useEffect(() => {
    refreshHealth()
    const timer = window.setInterval(refreshHealth, 30_000)
    return () => window.clearInterval(timer)
  }, [refreshHealth])

  // Load session list
  const refreshSessions = useCallback(async () => {
    try {
      const list = await listSessions()
      setSessions(list)
    } catch { /* server may be starting */ }
  }, [])

  useEffect(() => { refreshSessions() }, [refreshSessions])

  const openSession = useCallback(async (id) => {
    try {
      const s = await getSession(id)
      setActive(s)
    } catch (e) {
      console.error('Failed to load session', e)
    }
  }, [])

  const onNewResult = useCallback((result) => {
    setActive(result)
    refreshSessions()
    refreshHealth()
  }, [refreshHealth, refreshSessions])

  const onNewChat = useCallback(() => {
    setActive(null)
  }, [])

  return (
    <div className="app-shell">
      {serverOk === false && (
        <div className="server-banner">
          ⚠ Backend not reachable — run <code>uvicorn backend.main:app --reload --port 8000</code>
        </div>
      )}
      <Sidebar
        sessions={sessions}
        activeId={activeSession?.id}
        onSelect={openSession}
        onNewChat={onNewChat}
      />
      <main className="main-pane">
        <ChatPane
          session={activeSession}
          onResult={onNewResult}
          serverHealth={serverHealth}
        />
      </main>
    </div>
  )
}
