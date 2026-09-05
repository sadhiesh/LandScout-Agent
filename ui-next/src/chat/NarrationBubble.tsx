import { useEffect, useState } from 'react'
import type { TraceEvent } from '../lib/useTraceStream'
import { buildNarration } from './narration'
import styles from './NarrationBubble.module.css'

interface NarrationBubbleProps {
  events: TraceEvent[]
  isComplete: boolean
}

export default function NarrationBubble({ events, isComplete }: NarrationBubbleProps) {
  const [now, setNow] = useState(() => Date.now())
  const [collapsed, setCollapsed] = useState(false)

  useEffect(() => {
    if (isComplete) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [isComplete])

  useEffect(() => {
    if (isComplete && events.length > 8) setCollapsed(true)
  }, [isComplete, events.length])

  if (events.length === 0) return null

  const lines = buildNarration(events, isComplete, now)

  if (collapsed) {
    return (
      <div className={styles.wrap}>
        <button type="button" className={styles.collapsedBtn} onClick={() => setCollapsed(false)}>
          ▾ View journey ({lines.length} stages, {events.length} steps)
        </button>
      </div>
    )
  }

  return (
    <div className={styles.wrap}>
      {lines.map((line) => (
        <div key={line.stage} className={`${styles.stageRow} ${line.isActive ? styles.stageRowActive : styles.stageRowDone}`}>
          <span className={`${styles.dot} ${line.isActive ? styles.dotActive : styles.dotDone}`} />
          <div className={styles.headline}>
            {line.isComplete ? '✓ ' : ''}
            {line.headline}
            {line.expanded &&
              line.detailLines.map((d, i) => (
                <div key={i} className={styles.detail}>
                  {d}
                </div>
              ))}
            {line.warning && <div className={styles.warning}>⚠️ {line.warning}</div>}
          </div>
        </div>
      ))}
      {isComplete && (
        <button type="button" className={styles.collapsedBtn} onClick={() => setCollapsed(true)}>
          ▴ Collapse
        </button>
      )}
    </div>
  )
}
