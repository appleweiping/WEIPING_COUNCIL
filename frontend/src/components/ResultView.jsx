import { useState } from 'react'
import SafeMarkdown from './SafeMarkdown'
import './ResultView.css'

const PROTOCOL_META = {
  auto:       { icon: '◇', label: 'Auto',       color: '#22d3ee' },
  council:    { icon: '⚖', label: 'Council',    color: '#5b8af5' },
  debate:     { icon: '⚔', label: 'Debate',     color: '#f87171' },
  redteam:    { icon: '🔴', label: 'Red Team',   color: '#fb923c' },
  consensus:  { icon: '🤝', label: 'Consensus',  color: '#4ade80' },
  specialist: { icon: '🎯', label: 'Specialist', color: '#a78bfa' },
  tournament: { icon: '🏆', label: 'Tournament', color: '#fbbf24' },
}

const MODEL_COLORS = [
  '#5b8af5', '#4ade80', '#f87171', '#fbbf24', '#a78bfa', '#22d3ee',
]

function modelColor(modelId, index) {
  return MODEL_COLORS[index % MODEL_COLORS.length]
}

function shortModel(id) {
  if (!id) return '?'
  const parts = id.split('/')
  return parts[parts.length - 1].replace(/-\d+(\.\d+)*$/, '').replace(/-/g, ' ')
}

function ConfidenceBar({ value }) {
  const pct = Math.round((value || 0) * 100)
  const color = pct >= 70 ? '#4ade80' : pct >= 40 ? '#fbbf24' : '#f87171'
  return (
    <div className="conf-bar-wrap">
      <div className="conf-bar-track">
        <div className="conf-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="conf-bar-label" style={{ color }}>{pct}%</span>
    </div>
  )
}

function ModelTab({ models, activeIdx, onSelect }) {
  return (
    <div className="model-tabs">
      {models.map((m, i) => (
        <button
          key={m.id || i}
          className={`model-tab ${i === activeIdx ? 'model-tab--active' : ''}`}
          style={i === activeIdx ? { borderBottomColor: modelColor(m.id, i), color: modelColor(m.id, i) } : {}}
          onClick={() => onSelect(i)}
        >
          <span className="model-dot" style={{ background: modelColor(m.id, i) }} />
          {shortModel(m.id)}
        </button>
      ))}
    </div>
  )
}

const SIMPLE_STAGE_FIELDS = [
  ['final', 'Final synthesis'],
  ['judge', 'Judge'],
  ['verdict', 'Verdict'],
  ['attacker', 'Attacker'],
  ['critique', 'Critique'],
  ['classification', 'Classification'],
  ['specialist', 'Specialist'],
  ['answer', 'Specialist answer'],
  ['winner', 'Winner'],
  ['tier', 'Tier'],
  ['model', 'Model'],
  ['response', 'Response'],
]

function EvidenceText({ label, value }) {
  if (typeof value !== 'string' || !value) return null
  return (
    <div className="stage-verdict">
      <span className="verdict-label">{label}</span>
      <div className="md"><SafeMarkdown>{value}</SafeMarkdown></div>
    </div>
  )
}

function EvidenceMap({ label, values }) {
  if (!values || typeof values !== 'object' || Array.isArray(values)) return null
  const entries = Object.entries(values)
  if (!entries.length) return null
  return (
    <div className="stage-verdict">
      <span className="verdict-label">{label}</span>
      {entries.map(([id, raw]) => {
        const value = typeof raw === 'string' ? raw : raw?.review
        if (typeof value !== 'string') return null
        return (
          <div key={id} className="stage-response md">
            <strong>{shortModel(id)}</strong>
            <SafeMarkdown>{value}</SafeMarkdown>
          </div>
        )
      })}
    </div>
  )
}

function ParticipantEvidence({ label, participant }) {
  if (!participant || typeof participant !== 'object') return null
  return (
    <div className="stage-verdict">
      <span className="verdict-label">{label}{participant.model ? ` · ${participant.model}` : ''}</span>
      <EvidenceText label="Argument" value={participant.argument} />
      <EvidenceText label="Rebuttal" value={participant.rebuttal} />
    </div>
  )
}

export function StageCard({ stage, index }) {
  const [activeModel, setActiveModel] = useState(0)
  const responses = stage.responses || {}
  const modelIds = Object.keys(responses)

  return (
    <div className="stage-card">
      <div className="stage-card-header">
        <span className="stage-num">{index + 1}</span>
        <span className="stage-name">{stage.name || `Stage ${index + 1}`}</span>
        {stage.agreement_ratio != null && (
          <span className="stage-agreement">
            Agreement: <strong>{Math.round(stage.agreement_ratio * 100)}%</strong>
          </span>
        )}
      </div>

      {modelIds.length > 0 && (
        <>
          <ModelTab
            models={modelIds.map(id => ({ id }))}
            activeIdx={activeModel}
            onSelect={setActiveModel}
          />
          <div className="stage-response md">
            <SafeMarkdown>
              {responses[modelIds[activeModel]] || ''}
            </SafeMarkdown>
          </div>
        </>
      )}

      <ParticipantEvidence label="Proponent" participant={stage.proponent} />
      <ParticipantEvidence label="Opponent" participant={stage.opponent} />
      <EvidenceMap label="Peer reviews" values={stage.reviews} />
      <EvidenceMap label="Verifications" values={stage.verifications} />

      {SIMPLE_STAGE_FIELDS.map(([field, label]) => (
        <EvidenceText key={field} label={label} value={stage[field]} />
      ))}

      {Array.isArray(stage.matchups) && stage.matchups.map((matchup, matchupIndex) => (
        <div key={`matchup-${matchupIndex}`} className="stage-verdict">
          <span className="verdict-label">
            Matchup {matchup.a || '?'} vs {matchup.b || '?'} · winner {matchup.winner || '?'}
          </span>
          <div className="md"><SafeMarkdown>{matchup.verdict || ''}</SafeMarkdown></div>
        </div>
      ))}

      {Array.isArray(stage.subtasks) && stage.subtasks.map((subtask, subtaskIndex) => (
        <div key={`subtask-${subtaskIndex}`} className="stage-verdict">
          <span className="verdict-label">
            Subtask {subtaskIndex + 1} · {subtask.model || '?'} · {subtask.status || 'unknown'}
          </span>
          <EvidenceText label="Description" value={subtask.desc} />
          <EvidenceText label="Result" value={subtask.result} />
        </div>
      ))}

      {(stage.iterations != null || stage.converged != null || Array.isArray(stage.scores)) && (
        <div className="stage-verdict">
          <span className="verdict-label">Refinement evidence</span>
          <code>
            iterations={String(stage.iterations ?? '?')} · converged={String(stage.converged ?? '?')}
            {Array.isArray(stage.scores) ? ` · scores=${stage.scores.join(', ')}` : ''}
          </code>
        </div>
      )}
    </div>
  )
}

function AuditTrail({ trail }) {
  const [open, setOpen] = useState(false)
  if (!trail?.length) return null
  return (
    <div className="audit-wrap">
      <button className="audit-toggle" onClick={() => setOpen(o => !o)}>
        {open ? '▾' : '▸'} Audit Trail <span className="audit-count">{trail.length} steps</span>
      </button>
      {open && (
        <div className="audit-list">
          {trail.map((step, i) => (
            <div key={i} className="audit-step">
              <span className="audit-step-num">{i + 1}</span>
              <code className="audit-step-data">{JSON.stringify(step)}</code>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function RuntimeEvidence({ session }) {
  const providers = session.provider_health || []
  const metrics = session.metrics || {}
  const traces = session.model_call_traces || []
  const warnings = session.warnings || []
  const routing = session.routing || {}
  const readyCount = providers.filter(p => p.ready).length
  const selectedRoute = routing.selected_protocol || routing.tier || 'unknown'

  return (
    <div className={`runtime-evidence ${session.degraded ? 'runtime-evidence--degraded' : ''}`}>
      <div className="runtime-evidence-header">
        <span className="runtime-evidence-title">Runtime Evidence</span>
        <span className="runtime-evidence-state">{session.degraded ? 'degraded' : 'ready'}</span>
      </div>

      <div className="runtime-grid">
        <div>
          <span className="runtime-label">Route</span>
          <strong>{routing.mode ? `${routing.mode} → ${selectedRoute}` : 'legacy session'}</strong>
        </div>
        <div>
          <span className="runtime-label">Providers</span>
          <strong>{readyCount}/{providers.length || 0} ready</strong>
        </div>
        <div>
          <span className="runtime-label">Total</span>
          <strong>{Math.round(metrics.total_ms || 0)}ms</strong>
        </div>
        <div>
          <span className="runtime-label">Calls</span>
          <strong>{traces.length}</strong>
        </div>
      </div>

      {warnings.length > 0 && (
        <div className="runtime-warnings">
          {warnings.map((warning, i) => (
            <div key={i} className="runtime-warning">{warning}</div>
          ))}
        </div>
      )}

      {providers.length > 0 && (
        <div className="provider-list">
          {providers.map((provider, i) => (
            <div key={`${provider.role}-${i}`} className="provider-row">
              <span className={`provider-dot ${provider.ready ? 'provider-dot--ready' : ''}`} />
              <span className="provider-name">{provider.name || provider.role}</span>
              <span className="provider-model">{provider.model_id}</span>
              <span className="provider-state">{provider.ready ? 'ready' : 'missing config'}</span>
            </div>
          ))}
        </div>
      )}

      {traces.length > 0 && (
        <details className="trace-details">
          <summary>Model call traces ({traces.length})</summary>
          <div className="trace-list">
            {traces.map((trace, i) => (
              <div key={`${trace.role}-${i}`} className="trace-row">
                <span>{trace.role}</span>
                <code>{trace.model_id}</code>
                <span>{trace.attempts} attempt{trace.attempts === 1 ? '' : 's'}</span>
                <span>{Math.round(trace.latency_ms || 0)}ms</span>
                <span className={trace.error_kind ? 'trace-error' : 'trace-ok'}>
                  {trace.error_kind || 'ok'}
                </span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  )
}

export default function ResultView({ session }) {
  const [showStages, setShowStages] = useState(false)
  if (!session) return null

  const meta = PROTOCOL_META[session.protocol] || PROTOCOL_META.council
  const stages = session.stages || []
  const dissent = session.dissent || []

  return (
    <div className="result-view">
      {/* Query echo */}
      <div className="result-query">
        <span className="result-query-icon">💬</span>
        <span className="result-query-text">{session.query}</span>
      </div>

      {/* Protocol badge + confidence */}
      <div className="result-meta-row">
        <span className="proto-badge" style={{ background: meta.color + '22', color: meta.color, borderColor: meta.color + '55' }}>
          {meta.icon} {meta.label}
        </span>
        {session.degraded && <span className="degraded-badge">degraded</span>}
        <div className="result-confidence">
          <span className="conf-label">Confidence</span>
          <ConfidenceBar value={session.confidence} />
        </div>
      </div>

      <RuntimeEvidence session={session} />

      {/* Final answer */}
      <div className="result-answer">
        <div className="result-answer-header">
          <span className="answer-icon">✦</span>
          <span className="answer-label">Final Answer</span>
        </div>
        <div className="result-answer-body md">
          <SafeMarkdown>
            {session.final_answer || ''}
          </SafeMarkdown>
        </div>
      </div>

      {/* Dissent */}
      {dissent.length > 0 && (
        <div className="result-dissent">
          <div className="dissent-header">⚠ Dissenting Views ({dissent.length})</div>
          {dissent.map((d, i) => (
            <div key={i} className="dissent-item md">
              <SafeMarkdown>
                {d.length > 400 ? d.slice(0, 400) + '…' : d}
              </SafeMarkdown>
            </div>
          ))}
        </div>
      )}

      {/* Stages toggle */}
      {stages.length > 0 && (
        <div className="stages-section">
          <button className="stages-toggle" onClick={() => setShowStages(s => !s)}>
            {showStages ? '▾' : '▸'} Deliberation Stages
            <span className="stages-count">{stages.length} stages</span>
          </button>
          {showStages && (
            <div className="stages-list">
              {stages.map((stage, i) => (
                <StageCard key={i} stage={stage} index={i} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Audit trail */}
      <AuditTrail trail={session.audit_trail} />
    </div>
  )
}
