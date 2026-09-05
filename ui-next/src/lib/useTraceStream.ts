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

export interface UseTraceStreamReturn {
  runId: string
  panels: PanelState
  isConnected: boolean
  beginRun: () => string
  resetStream: () => void
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

/**
 * Owns the active run_id and SSE subscription. Chat must call beginRun() and
 * send the returned id as X-Run-ID so the Rail/Inspector/Showcase views share
 * one stream — same contract as the existing console (docs/architecture.md).
 */
export function useTraceStream(): UseTraceStreamReturn {
  const [runId, setRunId] = useState(() => crypto.randomUUID())
  const [panels, setPanels] = useState<PanelState>(EMPTY_PANELS)
  const [isConnected, setIsConnected] = useState(false)
  const eventSourceRef = useRef<EventSource | null>(null)
  const runIdRef = useRef(runId)

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
    const newRunId = crypto.randomUUID()
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
    const fresh = crypto.randomUUID()
    runIdRef.current = fresh
    setRunId(fresh)
    openStream(fresh)
  }, [openStream])

  return { runId, panels, isConnected, beginRun, resetStream }
}
