import { useCallback, useEffect, useRef, useState } from 'react'

export type PanelId = 'sessions' | 'chat' | 'workspace'

interface Fractions {
  sessions: number
  chat: number
}

const MIN_PX: Record<PanelId, number> = {
  sessions: 210,
  chat: 420,
  workspace: 340,
}

const DEFAULT_FRACTIONS: Fractions = { sessions: 0.24, chat: 0.76 }
const STORAGE_KEY = 'landscout-next-panel-layout-v2'

function loadStored(): { fractions: Fractions; sessionsCollapsed: boolean } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { fractions: DEFAULT_FRACTIONS, sessionsCollapsed: false }
    const parsed = JSON.parse(raw)
    return {
      fractions: { ...DEFAULT_FRACTIONS, ...parsed.fractions },
      sessionsCollapsed: Boolean(parsed.sessionsCollapsed),
    }
  } catch {
    return { fractions: DEFAULT_FRACTIONS, sessionsCollapsed: false }
  }
}

export function usePanelLayout() {
  const initial = loadStored()
  const [fractions, setFractions] = useState<Fractions>(initial.fractions)
  const [manualSessionsCollapsed, setManualSessionsCollapsed] = useState(initial.sessionsCollapsed)
  const [isNarrow, setIsNarrow] = useState(() => window.matchMedia('(max-width: 1180px)').matches)
  const [narrowSessionsOpen, setNarrowSessionsOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const drag = useRef<{
    startX: number
    startSessions: number
    startChat: number
    containerWidth: number
  } | null>(null)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ fractions, sessionsCollapsed: manualSessionsCollapsed }))
  }, [fractions, manualSessionsCollapsed])

  useEffect(() => {
    const query = window.matchMedia('(max-width: 1180px)')
    const onChange = (event: MediaQueryListEvent) => {
      setIsNarrow(event.matches)
      setNarrowSessionsOpen(false)
    }
    setIsNarrow(query.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  const sessionsCollapsed = isNarrow ? !narrowSessionsOpen : manualSessionsCollapsed

  const toggleSessions = useCallback(() => {
    if (isNarrow) {
      setNarrowSessionsOpen((value) => !value)
      return
    }
    setManualSessionsCollapsed((value) => !value)
  }, [isNarrow])

  const onHandleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (sessionsCollapsed) return
      const containerWidth = containerRef.current?.getBoundingClientRect().width ?? 1200
      drag.current = {
        startX: e.clientX,
        startSessions: fractions.sessions,
        startChat: fractions.chat,
        containerWidth,
      }
      document.body.style.userSelect = 'none'
      document.body.style.cursor = 'col-resize'

      const onMove = (ev: MouseEvent) => {
        const d = drag.current
        if (!d) return
        const deltaPx = ev.clientX - d.startX
        const deltaFr = deltaPx / d.containerWidth
        const minSessions = MIN_PX.sessions / d.containerWidth
        const minChat = MIN_PX.chat / d.containerWidth
        const nextSessions = Math.max(minSessions, d.startSessions + deltaFr)
        const nextChat = Math.max(minChat, d.startChat - deltaFr)
        setFractions({ sessions: nextSessions, chat: nextChat })
      }
      const onUp = () => {
        drag.current = null
        document.body.style.userSelect = ''
        document.body.style.cursor = ''
        window.removeEventListener('mousemove', onMove)
        window.removeEventListener('mouseup', onUp)
      }
      window.addEventListener('mousemove', onMove)
      window.addEventListener('mouseup', onUp)
    },
    [fractions, sessionsCollapsed],
  )

  const columnTemplates: [string, string, string] = [
    sessionsCollapsed ? '0px' : `minmax(${MIN_PX.sessions}px, ${fractions.sessions}fr)`,
    `minmax(${MIN_PX.chat}px, ${fractions.chat}fr)`,
    `minmax(${MIN_PX.workspace}px, 0.58fr)`,
  ]

  return {
    containerRef,
    columnTemplates,
    sessionsCollapsed,
    toggleSessions,
    onHandleMouseDown,
  }
}
