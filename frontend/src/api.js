/* api.js — thin wrapper around the backend REST API */

const BASE = '/api'

export async function submitQuery(query, protocol = 'council', context = null, options = {}) {
  const res = await fetch(`${BASE}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, protocol, context }),
    signal: options.signal,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export async function listSessions() {
  const res = await fetch(`${BASE}/sessions`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function getSession(id) {
  const res = await fetch(`${BASE}/sessions/${id}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function listModels() {
  const res = await fetch(`${BASE}/models`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function listProtocols() {
  const res = await fetch(`${BASE}/protocols`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function healthCheck() {
  const res = await fetch(`${BASE}/health`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
