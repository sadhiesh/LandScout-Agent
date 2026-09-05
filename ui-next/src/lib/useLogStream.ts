import { useState, useEffect, useRef, useCallback } from 'react'

export interface LogLine {
  service: string
  line: string
}

export interface UseLogStreamReturn {
  logs: LogLine[]
  isConnected: boolean
  clearLogs: () => void
}

export function useLogStream(): UseLogStreamReturn {
  const [logs, setLogs] = useState<LogLine[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const eventSourceRef = useRef<EventSource | null>(null)

  useEffect(() => {
    fetch('/debug/logs/tail?lines=100')
      .then((res) => res.json())
      .then((data) => {
        const initial: LogLine[] = []
        for (const [service, lines] of Object.entries(data)) {
          if (Array.isArray(lines)) {
            lines.forEach((line: string) => {
              if (line) initial.push({ service, line })
            })
          }
        }
        setLogs(initial)
      })
      .catch((err) => console.error('[LogStream] Failed to fetch backfill:', err))
  }, [])

  useEffect(() => {
    const eventSource = new EventSource('/debug/logs/stream')
    eventSourceRef.current = eventSource

    eventSource.onopen = () => setIsConnected(true)
    eventSource.onerror = () => setIsConnected(false)
    eventSource.onmessage = (event) => {
      try {
        const logLine: LogLine = JSON.parse(event.data)
        setLogs((prev) => {
          const next = [...prev, logLine]
          return next.length > 1000 ? next.slice(-1000) : next
        })
      } catch (err) {
        console.error('[LogStream] Failed to parse event:', err)
      }
    }

    return () => eventSource.close()
  }, [])

  const clearLogs = useCallback(() => setLogs([]), [])

  return { logs, isConnected, clearLogs }
}
