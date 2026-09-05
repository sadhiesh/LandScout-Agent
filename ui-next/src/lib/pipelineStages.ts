/**
 * Shared mapping from a raw trace event to a pipeline stage / icon.
 * Used by both the live narration bubble and the Transparency Rail so the
 * two renderings of the same event stream never drift apart.
 */

import type { TraceEvent } from './useTraceStream'

export const STAGE_ORDER = ['Parse', 'Reasoning', 'Search', 'Enrich', 'Score'] as const
export type Stage = (typeof STAGE_ORDER)[number] | 'Pipeline'

export function stageForEvent(event: Pick<TraceEvent, 'kind' | 'agent' | 'summary' | 'data'>): Stage {
  const summary = event.summary?.toLowerCase() ?? ''
  const relatedActor = [
    event.agent,
    event.data?.subagent,
    event.data?.target_agent,
    event.data?.target,
    event.data?.source,
  ]
    .filter((value): value is string => typeof value === 'string')
    .join(' ')
    .toLowerCase()

  if (event.kind === 'thought' && summary.includes('criteria')) return 'Parse'
  if (event.kind === 'memory_read' || event.kind === 'memory_write') return 'Parse'
  if (relatedActor.includes('scout') || summary.includes('landwatch')) return 'Search'
  if (
    relatedActor.includes('enricher') ||
    summary.includes('enrich') ||
    summary.includes('cad') ||
    summary.includes('flood') ||
    summary.includes('county_comps')
  )
    return 'Enrich'
  if (relatedActor.includes('scorer') || summary.includes('scor') || summary.includes('rationale')) return 'Score'
  // Any other "thought" is the criteria-sufficiency gate reasoning through a
  // candidate interpretation (docs/architecture.md) — that's CoT activity,
  // not an unlabeled pipeline step, so it must not collapse into 'Pipeline'.
  if (event.kind === 'thought') return 'Reasoning'
  return 'Pipeline'
}

/**
 * Reads the active reasoning mode from event metadata rather than hardcoding
 * it, so the UI can never claim Tree-of-Thoughts is active when only
 * Chain-of-Thought is implemented (ADR 0018). Shared by the Rail and
 * Showcase Mode so both readings of the same stream can't drift apart.
 */
export function reasoningMode(events: Pick<TraceEvent, 'kind' | 'data'>[]): string {
  const thought = [...events].reverse().find((e) => e.kind === 'thought')
  const mode = thought?.data?.reasoning_mode
  return typeof mode === 'string' && mode ? mode : 'Chain-of-Thought (CoT)'
}

/** Compact form for tight spaces, e.g. "Chain-of-Thought (CoT)" -> "CoT". */
export function reasoningModeShort(mode: string): string {
  const match = mode.match(/\(([^)]+)\)/)
  return match ? match[1] : mode
}

const KNOWN_AGENTS: Record<string, string> = {
  supervisor: 'Supervisor',
  scout: 'Scout',
  enricher: 'Enricher',
  scorer: 'Scorer',
}

/** Display name for a trace event's actor, e.g. "scout" -> "Scout". */
export function actorLabel(agent?: string | null): string {
  if (!agent) return 'System'
  return KNOWN_AGENTS[agent.toLowerCase()] ?? agent.charAt(0).toUpperCase() + agent.slice(1)
}

/**
 * The "Event Type" column of the Actor - Event Type - Action model every
 * rendering of the trace (Rail, Inspector, narration) should share, so a
 * tool call, a memory op, and an agent handoff never look alike. Reasoning
 * mode is read per-event rather than hardcoded, same reason as reasoningMode().
 * memory_read/memory_write are deliberately labeled "Memory", not "RAG" —
 * this project has no vector/embedding retrieval, only a deterministic
 * persisted-score short-circuit (docs/architecture.md).
 */
export function eventTypeLabel(event: Pick<TraceEvent, 'kind' | 'data'>): string {
  const d = event.data ?? {}
  switch (event.kind) {
    case 'thought':
      return `Reasoning - ${reasoningModeShort(reasoningMode([event]))}`
    case 'tool_call':
      return 'Tool Call'
    case 'tool_result':
      return 'Tool Result'
    case 'memory_read':
      return 'Memory (read)'
    case 'memory_write':
      return 'Memory (write)'
    case 'context':
      return 'Context'
    case 'route':
      return 'Routing'
    case 'a2a_send': {
      const target = d.target_agent ?? d.target
      return target ? `Agent - ${actorLabel(target)}` : 'Agent Handoff'
    }
    case 'a2a_recv': {
      const source = d.target_agent ?? d.source
      return source ? `Agent - ${actorLabel(source)}` : 'Agent Handoff'
    }
    case 'subagent_start':
    case 'subagent_finish': {
      const subagent = d.subagent
      return subagent ? `Agent - ${actorLabel(subagent)}` : 'Agent'
    }
    case 'error':
      return 'Error'
    default:
      return event.kind
  }
}

export function iconForKind(kind: string): string {
  switch (kind) {
    case 'thought':
      return '💭'
    case 'tool_call':
      return '🔧'
    case 'tool_result':
      return '✓'
    case 'error':
      return '⚠️'
    case 'memory_read':
      return '📚'
    case 'memory_write':
      return '💾'
    case 'context':
      return '📋'
    case 'route':
      return '→'
    case 'a2a_send':
      return '📤'
    case 'a2a_recv':
      return '📥'
    case 'subagent_start':
      return '▶'
    case 'subagent_finish':
      return '◼'
    default:
      return '·'
  }
}

export interface StageGroup {
  name: Stage
  events: TraceEvent[]
  startedAt: number | null
  finishedAt: number | null
  hasWarning: boolean
}

/** Returns the stage of the newest timestamped event, independent of group display order. */
export function latestStage(events: TraceEvent[]): Stage | null {
  if (events.length === 0) return null

  const timestamped = events
    .map((event, index) => ({ event, index, timestamp: Date.parse(event.ts) }))
    .filter((entry) => !Number.isNaN(entry.timestamp))

  if (timestamped.length === 0) return stageForEvent(events[events.length - 1])

  const latest = timestamped.reduce((candidate, entry) =>
    entry.timestamp > candidate.timestamp ||
    (entry.timestamp === candidate.timestamp && entry.index > candidate.index)
      ? entry
      : candidate,
  )
  return stageForEvent(latest.event)
}

function explicitlyCompletesStage(event: TraceEvent): boolean {
  if (event.kind === 'subagent_finish') return true
  return event.data?.stage_complete === true || event.data?.pipeline_stage_complete === true
}

/**
 * A stage is complete only after a later pipeline stage starts, a completion
 * event is received, or the overall run has ended.
 */
export function stageIsComplete(stage: Stage, events: TraceEvent[], isRunActive: boolean): boolean {
  const stageEvents = events.filter((event) => stageForEvent(event) === stage)
  if (stageEvents.length === 0) return false
  if (stageEvents.some(explicitlyCompletesStage)) return true
  if (!isRunActive) return true
  if (latestStage(events) === stage) return false

  const stageIndex = STAGE_ORDER.indexOf(stage as (typeof STAGE_ORDER)[number])
  if (stageIndex < 0) {
    return events.some((event) => stageForEvent(event) !== 'Pipeline')
  }
  return events.some((event) => {
    const eventIndex = STAGE_ORDER.indexOf(stageForEvent(event) as (typeof STAGE_ORDER)[number])
    return eventIndex > stageIndex
  })
}

/** Groups a flat event list into ordered stage buckets with timing. */
export function groupByStage(events: TraceEvent[]): StageGroup[] {
  const byName = new Map<Stage, StageGroup>()

  events.forEach((event) => {
    const name = stageForEvent(event)
    if (!byName.has(name)) {
      byName.set(name, { name, events: [], startedAt: null, finishedAt: null, hasWarning: false })
    }
    const group = byName.get(name)!
    group.events.push(event)
    const ts = Date.parse(event.ts)
    if (!Number.isNaN(ts)) {
      if (group.startedAt === null || ts < group.startedAt) group.startedAt = ts
      if (group.finishedAt === null || ts > group.finishedAt) group.finishedAt = ts
    }
    if (event.kind === 'error') group.hasWarning = true
  })

  const ordered: StageGroup[] = []
  STAGE_ORDER.forEach((name) => {
    const g = byName.get(name)
    if (g) ordered.push(g)
    byName.delete(name)
  })
  byName.forEach((g) => ordered.push(g))
  return ordered
}
