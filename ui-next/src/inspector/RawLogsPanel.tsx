import { useEffect, useRef, useState } from 'react'
import type { LogLine } from '../lib/useLogStream'
import styles from './RawLogsPanel.module.css'

interface RawLogsPanelProps {
  logs: LogLine[]
  isConnected: boolean
  onClear: () => void
}

const SERVICES = ['api', 'supervisor', 'scout', 'enricher', 'scorer', 'mcp']

export default function RawLogsPanel({ logs, isConnected, onClear }: RawLogsPanelProps) {
  const [serviceFilter, setServiceFilter] = useState('all')
  const [textFilter, setTextFilter] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)
  const endRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (autoScroll) endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs, autoScroll])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const onScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = container
      setAutoScroll(scrollHeight - scrollTop - clientHeight < 50)
    }
    container.addEventListener('scroll', onScroll)
    return () => container.removeEventListener('scroll', onScroll)
  }, [])

  const services = ['all', ...SERVICES]
  const filtered = logs.filter((l) => {
    if (serviceFilter !== 'all' && l.service !== serviceFilter) return false
    if (textFilter && !l.line.toLowerCase().includes(textFilter.toLowerCase())) return false
    return true
  })

  return (
    <div className={styles.panel}>
      <div className={styles.toolbar}>
        <div className={styles.filters}>
          <select className={styles.select} value={serviceFilter} onChange={(e) => setServiceFilter(e.target.value)}>
            {services.map((svc) => (
              <option key={svc} value={svc}>
                {svc === 'all' ? 'All Services' : svc}
              </option>
            ))}
          </select>
          <input
            className={styles.input}
            type="text"
            placeholder="Filter text..."
            value={textFilter}
            onChange={(e) => setTextFilter(e.target.value)}
          />
        </div>
        <div className={styles.actions}>
          <label className={styles.checkbox}>
            <input type="checkbox" checked={autoScroll} onChange={(e) => setAutoScroll(e.target.checked)} />
            Auto-scroll
          </label>
          <button type="button" className={styles.clearButton} onClick={onClear}>
            Clear
          </button>
          <span className={isConnected ? styles.connected : styles.disconnected}>
            {isConnected ? '● Live' : '○ Disconnected'}
          </span>
        </div>
      </div>

      <div className={styles.logsContainer} ref={containerRef}>
        {filtered.length === 0 && (
          <div className={styles.empty}>{logs.length === 0 ? 'No logs yet...' : 'No logs match filter'}</div>
        )}
        {filtered.map((log, idx) => (
          <div key={idx} className={styles.logLine}>
            <span className={styles.service} data-service={log.service}>
              [{log.service}]
            </span>
            <span className={styles.line}>{log.line}</span>
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <div className={styles.footer}>
        {filtered.length} / {logs.length} lines
      </div>
    </div>
  )
}
