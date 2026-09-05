/**
 * Full-bleed live agent org-chart — the capstone-showcase surface.
 * Reuses the same /events/{run_id} trace already flowing to the Rail/Inspector,
 * so it can render a live run without a separate replay feature.
 *
 * Reasoning-mode label comes from lib/pipelineStages's reasoningMode(), which
 * reads event metadata rather than hardcoding it, so it never claims
 * Tree-of-Thoughts is active when only Chain-of-Thought is implemented
 * (docs/architecture.md) — same helper the Rail uses, so the two can't drift.
 */
import { useMemo } from 'react'
import type { TraceEvent } from '../lib/useTraceStream'
import { reasoningMode } from '../lib/pipelineStages'
import styles from './ShowcaseMode.module.css'

interface ShowcaseModeProps {
  events: TraceEvent[]
  isRunning: boolean
  onRunSample: () => void
  onExit: () => void
}

const RECENCY_MS = 4000

const WORKERS: Array<{ id: string; label: string; role: string; icon: string }> = [
  { id: 'scout', label: 'Scout', role: 'Search LandWatch listings', icon: '🔭' },
  { id: 'enricher', label: 'Enricher', role: 'County CAD, flood, comps', icon: '🧩' },
  { id: 'scorer', label: 'Scorer', role: 'Deterministic scoring', icon: '📊' },
]

function lastEventFor(events: TraceEvent[], agent: string): TraceEvent | null {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].agent === agent) return events[i]
  }
  return null
}

function isRecent(event: TraceEvent | null, now: number): boolean {
  if (!event) return false
  const ts = Date.parse(event.ts)
  return !Number.isNaN(ts) && now - ts < RECENCY_MS
}

export default function ShowcaseMode({ events, isRunning, onRunSample, onExit }: ShowcaseModeProps) {
  const now = Date.now()

  const supervisorEvent = lastEventFor(events, 'supervisor')
  const supervisorActive = isRunning && isRecent(supervisorEvent, now)

  const memoryEvents = events.filter((e) => e.kind === 'memory_read' || e.kind === 'memory_write')
  const lastMemory = memoryEvents[memoryEvents.length - 1] ?? null

  const activeReasoningMode = useMemo(() => reasoningMode(events), [events])

  return (
    <div className={styles.wrap}>
      <div className={styles.topbar}>
        <div>
          <div className={styles.title}>Live Agent Architecture</div>
          <div className={styles.subtitle}>Supervisor-routed multi-agent pipeline — real trace, not a mockup</div>
        </div>
        <div className={styles.actions}>
          <button type="button" className={styles.runBtn} onClick={onRunSample} disabled={isRunning}>
            {isRunning ? 'Running…' : '▶ Run sample query'}
          </button>
          <button type="button" className={styles.exitBtn} onClick={onExit}>
            Exit → Default
          </button>
        </div>
      </div>

      <div className={styles.stage}>
        <div className={styles.tierLabel}>Supervisor</div>
        <div className={`${styles.node} ${supervisorActive ? styles.nodeActive : ''}`}>
          {supervisorActive && <span className={styles.pulseDot} />}
          <div className={styles.nodeIcon}>🧭</div>
          <div className={styles.nodeName}>Supervisor</div>
          <div className={styles.nodeRole}>Only agent that routes &amp; talks to others</div>
          <div className={styles.nodeStatus}>{supervisorEvent?.summary ?? 'Idle — waiting for a query'}</div>
        </div>

        <div className={`${styles.connector} ${supervisorActive ? styles.connectorActive : ''}`} />

        <div className={styles.tierLabel}>Workers (never call each other)</div>
        <div className={styles.row}>
          {WORKERS.map((w) => {
            const last = lastEventFor(events, w.id)
            const active = isRunning && isRecent(last, now)
            return (
              <div key={w.id} className={`${styles.node} ${active ? styles.nodeActive : ''}`}>
                {active && <span className={styles.pulseDot} />}
                <div className={styles.nodeIcon}>{w.icon}</div>
                <div className={styles.nodeName}>{w.label}</div>
                <div className={styles.nodeRole}>{w.role}</div>
                <div className={styles.nodeStatus}>{last?.summary ?? 'Idle'}</div>
              </div>
            )
          })}
        </div>

        <div className={`${styles.connector} ${isRunning ? styles.connectorActive : ''}`} />

        <div className={styles.mcpNode}>
          <div className={styles.mcpTitle}>MCP Server — :8010</div>
          <div className={styles.mcpSub}>Single tool gateway every agent reaches LandWatch/CAD/FEMA through</div>
        </div>
      </div>

      <div className={styles.footer}>
        <span className={styles.badge}>Reasoning: {activeReasoningMode}</span>
        <span className={`${styles.badge} ${lastMemory ? styles.memoryBadge : ''}`}>
          {lastMemory ? `Memory: ${lastMemory.kind === 'memory_write' ? 'wrote' : 'read'} — ${lastMemory.summary}` : 'Memory: idle'}
        </span>
        <span className={styles.badge}>{events.length} trace events this run</span>
      </div>
    </div>
  )
}
