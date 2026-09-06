/**
 * Trust-Rail + Command-Deck hybrid: per-stage accordion (Dock) with a
 * confidence/sources footer (Rail), and the door into the full Inspector.
 */
import { useState } from 'react'
import type { TraceEvent, TurnRecord } from '../lib/useTraceStream'
import {
  actorLabel,
  eventTypeLabel,
  groupByStage,
  latestStage,
  reasoningMode,
  reasoningModeShort,
  stageIsComplete,
} from '../lib/pipelineStages'
import styles from './TransparencyRail.module.css'

interface TransparencyRailProps {
  events: TraceEvent[]
  /** Completed turns from earlier in this session — see useTraceStream. */
  history: TurnRecord[]
  isRunActive: boolean
  onOpenInspector: () => void
}

function formatTurnTime(ts: string | null): string {
  if (!ts) return ''
  const parsed = new Date(ts)
  if (Number.isNaN(parsed.getTime())) return ''
  return parsed.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

/** Per-stage accordion for one turn's events. Shared by the live view and each history entry. */
function StageAccordion({ events, isRunActive }: { events: TraceEvent[]; isRunActive: boolean }) {
  const [openStage, setOpenStage] = useState<string | null>(null)
  const groups = groupByStage(events)
  const activeStage = latestStage(events)

  if (groups.length === 0) return null

  return (
    <div className={styles.stages}>
      {groups.map((group) => {
        const isOpen = openStage === group.name || (openStage === null && group.name === activeStage && isRunActive)
        const isComplete = stageIsComplete(group.name, events, isRunActive)
        const isActive = isRunActive && group.name === activeStage && !isComplete
        const groupId = `stage-${group.name.toLowerCase()}-${events[0]?.run_id ?? 'live'}`
        const duration =
          group.startedAt != null && group.finishedAt != null
            ? Math.max(0, group.finishedAt - group.startedAt)
            : null
        return (
          <div key={group.name} className={styles.stage}>
            <button
              type="button"
              className={styles.stageHead}
              onClick={() => setOpenStage(isOpen ? '' : group.name)}
              aria-expanded={isOpen}
              aria-controls={`${groupId}-body`}
              id={`${groupId}-button`}
            >
              <span
                className={`${styles.dot} ${
                  group.hasWarning
                    ? styles.dotWarn
                    : isActive
                      ? styles.dotActive
                      : isComplete
                        ? styles.dotDone
                        : styles.dotPending
                }`}
              />
              <span className={styles.stageName}>
                {group.name === 'Reasoning'
                  ? `Reasoning (${reasoningModeShort(reasoningMode(group.events))})`
                  : group.name}
              </span>
              <span className={styles.stageMeta}>{group.events.length} steps</span>
              {duration != null && <span className={styles.duration}>{duration < 1000 ? '<1s' : `${(duration / 1000).toFixed(1)}s`}</span>}
              <span>{isOpen ? '▾' : '▸'}</span>
            </button>
            {isOpen && (
              <div
                className={styles.stageBody}
                id={`${groupId}-body`}
                role="region"
                aria-labelledby={`${groupId}-button`}
              >
                {group.events.slice(-6).map((e, i) => (
                  <div key={i} className={styles.stepLine}>
                    <span className={styles.stepTag}>
                      {actorLabel(e.agent)} · {eventTypeLabel(e)}
                    </span>
                    {e.summary}
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default function TransparencyRail({
  events,
  history,
  isRunActive,
  onOpenInspector,
}: TransparencyRailProps) {
  const groups = groupByStage(events)
  const toolCalls = events.filter((e) => e.kind === 'tool_call')
  const toolResults = events.filter((e) => e.kind === 'tool_result')
  const errors = events.filter((e) => e.kind === 'error')
  const confidence = toolCalls.length === 0 ? null : Math.round((toolResults.length / toolCalls.length) * 100)
  const sources = Array.from(new Set(toolCalls.map((e) => e.data?.tool).filter(Boolean))) as string[]
  const hasAnything = groups.length > 0 || history.length > 0

  return (
    <section className={styles.rail}>
      <header className={styles.header}>
        <div>
          <div className={styles.title}>Multi-agent observability</div>
          <div className={styles.subtitle}>See how each recommendation was produced.</div>
        </div>
        <div className={`${styles.runStatus} ${isRunActive ? styles.running : ''}`}>
          <span />
          {isRunActive ? 'Live' : events.length > 0 ? 'Completed' : 'Ready'}
        </div>
      </header>

      {!hasAnything ? (
        <div className={styles.empty}>
          <div className={styles.emptyGlyph}>◎</div>
          <strong>Agent activity appears here</strong>
          <span>Start a land search to follow parsing, search, enrichment, and scoring in real time.</span>
        </div>
      ) : (
        <div className={styles.scroll}>
          {history.length > 0 && (
            <details className={styles.historySection}>
              <summary className={styles.historySummary}>
                Previous turns this session ({history.length})
              </summary>
              <div className={styles.historyList}>
                {history.map((turn, idx) => (
                  <details key={turn.runId} className={styles.historyTurn}>
                    <summary className={styles.historyTurnSummary}>
                      <span>Turn {idx + 1}</span>
                      <span className={styles.historyTurnMeta}>
                        {turn.events.length} steps{formatTurnTime(turn.finishedAt) ? ` · ${formatTurnTime(turn.finishedAt)}` : ''}
                      </span>
                    </summary>
                    <StageAccordion events={turn.events} isRunActive={false} />
                  </details>
                ))}
              </div>
            </details>
          )}

          {groups.length > 0 && <StageAccordion events={events} isRunActive={isRunActive} />}
        </div>
      )}

      <div className={styles.footer}>
        {confidence != null && (
          <>
            <div className={styles.confRow}>
              <span>Tool confidence</span>
              <span>
                {confidence}% {errors.length > 0 ? `· ${errors.length} warning${errors.length > 1 ? 's' : ''}` : ''}
              </span>
            </div>
            <div className={styles.confTrack}>
              <div className={styles.confFill} style={{ width: `${confidence}%` }} />
            </div>
          </>
        )}
        {sources.length > 0 && (
          <div className={styles.sources}>
            {sources.map((s) => (
              <span key={s} className={styles.sourceTag}>
                {s}
              </span>
            ))}
          </div>
        )}
        <button type="button" className={styles.inspectorBtn} onClick={onOpenInspector}>
          Open Inspector
        </button>
      </div>
    </section>
  )
}
