import { useState, useEffect, useCallback, useRef } from 'react'

export interface TraceEvent {
  run_id: string
  ts: string
  agent: string
  kind: string
  summary: string
  data?: Record<string, any>
}

export interface PanelState {
  context: TraceEvent[]
  memory: TraceEvent[]
  tools: TraceEvent[]
  subagents: TraceEvent[]
  trace: TraceEvent[]
  thoughts: TraceEvent[]
  logs: TraceEvent[]
}

const EMPTY_PANELS: PanelState = {
  context: [],
  memory: [],
  tools: [],
  subagents: [],
  trace: [],
  thoughts: [],
  logs: [],
}

/** One completed turn's worth of trace events, kept after `beginRun()` moves on. */
export interface TurnRecord {
  runId: string
  events: TraceEvent[]
  startedAt: string | null
  finishedAt: string | null
}

export interface UseTraceStreamReturn {
  runId: string
  /** The live/current run only — unchanged contract, still resets on beginRun(). */
  panels: PanelState
  /** Completed turns for the active session, oldest first. Never cleared by beginRun(). */
  history: TurnRecord[]
  isConnected: boolean
  beginRun: () => string
  resetStream: () => void
  /** Hydrates `history` from Postgres for a session (page reload / session switch). */
  loadSessionHistory: (sessionId: string) => Promise<void>
}

function routeEvent(prev: PanelState, traceEvent: TraceEvent): PanelState {
  const next: PanelState = { ...prev, trace: [...prev.trace, traceEvent] }

  switch (traceEvent.kind) {
    case 'context':
      next.context = [...prev.context, traceEvent]
      break
    case 'memory_read':
    case 'memory_write':
      next.memory = [...prev.memory, traceEvent]
      break
    case 'tool_call':
    case 'tool_result':
      next.tools = [...prev.tools, traceEvent]
      break
    case 'subagent_start':
    case 'subagent_finish':
      next.subagents = [...prev.subagents, traceEvent]
      break
    case 'thought':
    case 'llm_call':
    case 'llm_response':
      next.thoughts = [...prev.thoughts, traceEvent]
      break
    case 'route':
    case 'a2a_send':
    case 'a2a_recv':
    case 'error':
      next.logs = [...prev.logs, traceEvent]
      break
    default:
      break
  }

  return next
}

function toTurnRecord(runId: string, events: TraceEvent[]): TurnRecord {
  return {
    runId,
    events,
    startedAt: events[0]?.ts ?? null,
    finishedAt: events[events.length - 1]?.ts ?? null,
  }
}

/** Groups a flat, chronologically-ordered event list into per-run turns. */
function groupIntoTurns(events: TraceEvent[]): TurnRecord[] {
  const byRun = new Map<string, TraceEvent[]>()
  const order: string[] = []
  events.forEach((event) => {
    if (!byRun.has(event.run_id)) {
      byRun.set(event.run_id, [])
      order.push(event.run_id)
    }
    byRun.get(event.run_id)!.push(event)
  })
  return order.map((runId) => toTurnRecord(runId, byRun.get(runId)!))
}

/**
 * Owns the active run_id and SSE subscription. Chat must call beginRun() and
 * send the returned id as X-Run-ID so the Rail/Inspector/Showcase views share
 * one stream — same contract as the existing console (docs/architecture.md).
 *
 * `panels` stays scoped to the live/current run only (unchanged behavior for
 * narration and the live stage view). Completed turns move into `history`
 * instead of being discarded, so multi-turn sessions keep their reasoning
 * trace until the session itself is switched or reset.
 */
export function useTraceStream(): UseTraceStreamReturn {
  const [runId, setRunId] = useState(() => crypto.randomUUID())
  const [panels, setPanels] = useState<PanelState>(EMPTY_PANELS)
  const [history, setHistory] = useState<TurnRecord[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const eventSourceRef = useRef<EventSource | null>(null)
  const runIdRef = useRef(runId)
  const panelsRef = useRef(panels)

  useEffect(() => {
    panelsRef.current = panels
  }, [panels])

  const attachHandlers = useCallback((eventSource: EventSource) => {
    eventSource.onopen = () => setIsConnected(true)
    eventSource.onerror = () => setIsConnected(false)
    eventSource.onmessage = (event) => {
      try {
        const traceEvent: TraceEvent = JSON.parse(event.data)
        setPanels((prev) => routeEvent(prev, traceEvent))
      } catch (err) {
        console.error('[TraceStream] Failed to parse event:', err)
      }
    }
  }, [])

  const openStream = useCallback(
    (nextRunId: string) => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
      }
      setIsConnected(false)
      const eventSource = new EventSource(`/events/${nextRunId}`)
      eventSourceRef.current = eventSource
      attachHandlers(eventSource)
    },
    [attachHandlers],
  )

  useEffect(() => {
    runIdRef.current = runId
    if (!eventSourceRef.current) {
      openStream(runId)
    }
  }, [runId, openStream])

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close()
    }
  }, [])

  const beginRun = useCallback(() => {
    const finishedRunId = runIdRef.current
    const finishedEvents = panelsRef.current.trace
    const newRunId = crypto.randomUUID()
    if (finishedEvents.length > 0) {
      setHistory((prev) => [...prev, toTurnRecord(finishedRunId, finishedEvents)])
    }
    runIdRef.current = newRunId
    setPanels(EMPTY_PANELS)
    setRunId(newRunId)
    openStream(newRunId)
    return newRunId
  }, [openStream])

  const resetStream = useCallback(() => {
    eventSourceRef.current?.close()
    eventSourceRef.current = null
    setIsConnected(false)
    setPanels(EMPTY_PANELS)
    setHistory([])
    const fresh = crypto.randomUUID()
    runIdRef.current = fresh
    setRunId(fresh)
    openStream(fresh)
  }, [openStream])

  const loadSessionHistory = useCallback(async (sessionId: string) => {
    if (!sessionId) return
    try {
      const res = await fetch(`/debug/sessions/${sessionId}/trace`)
      if (!res.ok) return
      const events: TraceEvent[] = await res.json()
      setHistory(groupIntoTurns(events))
    } catch (err) {
      console.error('[TraceStream] Failed to load session history:', err)
    }
  }, [])

  return { runId, panels, history, isConnected, beginRun, resetStream, loadSessionHistory }
}
