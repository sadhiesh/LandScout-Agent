/**
 * Generic renderer shared by Context/Memory/Tools/Subagents/Trace/Events/Thoughts —
 * seven of the Inspector's eight tabs are all TraceEvent[] with different filters;
 * only Raw Logs (a different shape, LogLine[]) needs its own component.
 */
import type { TraceEvent } from '../lib/useTraceStream'
import { iconForKind, actorLabel, eventTypeLabel } from '../lib/pipelineStages'
import styles from './EventList.module.css'

interface EventListProps {
  events: TraceEvent[]
  emptyLabel: string
}

function formatTs(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString(undefined, { hour12: false })
  } catch {
    return ts
  }
}

export default function EventList({ events, emptyLabel }: EventListProps) {
  if (events.length === 0) {
    return <div className={styles.panel}><div className={styles.empty}>{emptyLabel}</div></div>
  }

  return (
    <div className={styles.panel}>
      <div className={styles.items}>
        {events.map((event, idx) => (
          <div key={idx} className={`${styles.item} ${event.kind === 'error' ? styles.error : ''}`}>
            <div className={styles.row}>
              <span>
                <span className={styles.agent}>{actorLabel(event.agent)}</span>{' '}
                <span className={styles.kind}>
                  {iconForKind(event.kind)} {eventTypeLabel(event)}
                </span>
              </span>
              <span className={styles.ts}>{formatTs(event.ts)}</span>
            </div>
            <div className={styles.summary}>{event.summary}</div>
            {event.data && Object.keys(event.data).length > 0 && (
              <details className={styles.section}>
                <summary className={styles.sectionTitle}>Data</summary>
                <pre className={styles.code}>{JSON.stringify(event.data, null, 2).slice(0, 2000)}</pre>
              </details>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
