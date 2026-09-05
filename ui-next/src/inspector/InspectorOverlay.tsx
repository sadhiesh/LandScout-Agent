import { useEffect, useRef, useState } from 'react'
import type { PanelState } from '../lib/useTraceStream'
import { useLogStream } from '../lib/useLogStream'
import EventList from './EventList'
import RawLogsPanel from './RawLogsPanel'
import styles from './InspectorOverlay.module.css'

interface InspectorOverlayProps {
  panels: PanelState
  onClose: () => void
}

type TabId = 'context' | 'memory' | 'tools' | 'subagents' | 'trace' | 'events' | 'thoughts' | 'rawlogs'

export default function InspectorOverlay({ panels, onClose }: InspectorOverlayProps) {
  const [activeTab, setActiveTab] = useState<TabId>('trace')
  const [gridMode, setGridMode] = useState(false)
  const logStream = useLogStream()
  const closeRef = useRef<HTMLButtonElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    closeRef.current?.focus()
    return () => previous?.focus()
  }, [])

  const trapFocus = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Tab') return
    const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )
    if (!focusable?.length) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  const tabs: Array<{ id: TabId; label: string; count: number }> = [
    { id: 'context', label: 'Context', count: panels.context.length },
    { id: 'memory', label: 'Memory', count: panels.memory.length },
    { id: 'tools', label: 'Tools', count: panels.tools.length },
    { id: 'subagents', label: 'Subagents', count: panels.subagents.length },
    { id: 'trace', label: 'Trace', count: panels.trace.length },
    { id: 'events', label: 'Events', count: panels.logs.length },
    { id: 'thoughts', label: 'Thoughts', count: panels.thoughts.length },
    { id: 'rawlogs', label: 'Raw Logs', count: logStream.logs.length },
  ]

  const renderTab = (id: TabId) => {
    switch (id) {
      case 'context':
        return <EventList events={panels.context} emptyLabel="No context payloads yet" />
      case 'memory':
        return <EventList events={panels.memory} emptyLabel="No memory reads/writes yet" />
      case 'tools':
        return <EventList events={panels.tools} emptyLabel="No tool calls yet" />
      case 'subagents':
        return <EventList events={panels.subagents} emptyLabel="No subagent delegations yet" />
      case 'trace':
        return <EventList events={panels.trace} emptyLabel="No trace events yet" />
      case 'events':
        return <EventList events={panels.logs} emptyLabel="No routing/A2A events yet" />
      case 'thoughts':
        return <EventList events={panels.thoughts} emptyLabel="No thoughts recorded yet" />
      case 'rawlogs':
        return <RawLogsPanel logs={logStream.logs} isConnected={logStream.isConnected} onClear={logStream.clearLogs} />
    }
  }

  return (
    <div ref={dialogRef} className={styles.overlay} role="dialog" aria-modal="true" aria-label="Agent Inspector" onKeyDown={trapFocus}>
      <div className={styles.topbar}>
        <div className={styles.title}>🔎 Agent Inspector</div>
        <button ref={closeRef} type="button" className={styles.closeBtn} onClick={onClose} aria-label="Close inspector">
          ✕
        </button>
      </div>

      <div className={styles.toolbar}>
        <div className={styles.tabs}>
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={`${styles.tab} ${activeTab === tab.id ? styles.active : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
              {tab.count > 0 && <span className={styles.badge}>{tab.count}</span>}
            </button>
          ))}
        </div>
        <button
          type="button"
          className={`${styles.gridToggle} ${gridMode ? styles.gridActive : ''}`}
          onClick={() => setGridMode((v) => !v)}
        >
          {gridMode ? '⊟ Tabs' : '⊞ Grid'}
        </button>
      </div>

      <div className={styles.content}>
        {gridMode ? (
          <div className={styles.grid}>
            {tabs.map((tab) => (
              <div key={tab.id} className={styles.gridPanel}>
                <div className={styles.gridPanelHeader}>
                  {tab.label}
                  {tab.count > 0 && <span className={styles.badge}>{tab.count}</span>}
                </div>
                <div className={styles.gridPanelContent}>{renderTab(tab.id)}</div>
              </div>
            ))}
          </div>
        ) : (
          renderTab(activeTab)
        )}
      </div>
    </div>
  )
}
