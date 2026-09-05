import { useMemo, useState } from 'react'
import type { Session } from '../lib/useSession'
import styles from './SessionSidebar.module.css'

interface SessionSidebarProps {
  sessions: Session[]
  currentSessionId: string | null
  onNewSession: () => void
  onSelectSession: (sessionId: string) => void
  onSwitchUser: () => void
  displayName: string | null
  collapsed: boolean
  onToggleCollapse: () => void
}

function formatWhen(iso: string | undefined): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  } catch {
    return ''
  }
}

export default function SessionSidebar({
  sessions,
  currentSessionId,
  onNewSession,
  onSelectSession,
  onSwitchUser,
  displayName,
  collapsed,
  onToggleCollapse,
}: SessionSidebarProps) {
  const [query, setQuery] = useState('')
  const filteredSessions = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    if (!normalized) return sessions
    return sessions.filter((session) => (session.title || 'Untitled search').toLowerCase().includes(normalized))
  }, [query, sessions])

  if (collapsed) {
    return null
  }

  return (
    <aside className={styles.sidebar}>
      <div className={styles.top}>
        <button type="button" className={styles.newBtn} onClick={onNewSession}>
          <span>+</span> New Search
        </button>
        <button type="button" className={styles.headerBtn} onClick={onToggleCollapse} aria-label="Hide sessions">
          ◁
        </button>
      </div>

      {displayName && (
        <div className={styles.userRow}>
          <div className={styles.userLabel}>
            <span className={styles.userName}>{displayName}</span>
            <span className={styles.userHint}>Signed in</span>
          </div>
          <button type="button" className={styles.switchBtn} onClick={onSwitchUser}>
            Switch
          </button>
        </div>
      )}

      <label className={styles.search}>
        <span aria-hidden>⌕</span>
        <span className={styles.srOnly}>Search sessions</span>
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search sessions" />
      </label>

      <div className={styles.sectionTitle}>Recent sessions</div>

      <div className={styles.list}>
        {filteredSessions.length === 0 ? (
          <div className={styles.empty}>{sessions.length === 0 ? 'No previous searches yet' : 'No sessions match'}</div>
        ) : (
          filteredSessions.map((s) => (
            <button
              key={s.session_id}
              type="button"
              className={`${styles.item} ${s.session_id === currentSessionId ? styles.active : ''}`}
              onClick={() => onSelectSession(s.session_id)}
            >
              <div className={styles.itemTitle}>{s.title || 'Untitled search'}</div>
              <div className={styles.itemMeta}>
                <span>{s.run_count} searches</span>
                <span>{formatWhen(s.last_seen_at)}</span>
              </div>
            </button>
          ))
        )}
      </div>
    </aside>
  )
}
