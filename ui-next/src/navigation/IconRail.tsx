import ThemeSwitcher from '../lib/ThemeSwitcher'
import LandScoutLogo from '../branding/LandScoutLogo'
import styles from './IconRail.module.css'

interface IconRailProps {
  sessionsOpen: boolean
  onNewSearch: () => void
  onOpenChat: () => void
  onToggleSessions: () => void
  onOpenInspector: () => void
  onOpenShowcase: () => void
}

function RailIcon({ name }: { name: 'home' | 'sessions' | 'inspector' | 'showcase' | 'plus' }) {
  const paths = {
    home: <path d="M3 10.5 12 3l9 7.5v9a1.5 1.5 0 0 1-1.5 1.5h-5v-6h-5v6h-5A1.5 1.5 0 0 1 3 19.5z" />,
    sessions: <path d="M5 5.5h14M5 12h14M5 18.5h9" />,
    inspector: (
      <>
        <circle cx="11" cy="11" r="6" />
        <path d="m16 16 5 5M11 8v6M8 11h6" />
      </>
    ),
    showcase: (
      <>
        <rect x="3" y="4" width="18" height="13" rx="2" />
        <path d="M8 21h8M12 17v4M8 9h8M8 12h5" />
      </>
    ),
    plus: <path d="M12 5v14M5 12h14" />,
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {paths[name]}
    </svg>
  )
}

export default function IconRail({
  sessionsOpen,
  onNewSearch,
  onOpenChat,
  onToggleSessions,
  onOpenInspector,
  onOpenShowcase,
}: IconRailProps) {
  return (
    <nav className={styles.rail} aria-label="Primary">
      <div className={styles.brand} aria-label="LandScout">
        <LandScoutLogo compact />
      </div>
      <button type="button" className={`${styles.item} ${styles.primary}`} onClick={onNewSearch} aria-label="New search">
        <RailIcon name="plus" />
        <span className={styles.tooltip}>New search</span>
      </button>
      <div className={styles.group}>
        <button type="button" className={`${styles.item} ${styles.active}`} onClick={onOpenChat} aria-label="Open land search">
          <RailIcon name="home" />
          <span className={styles.tooltip}>Land search</span>
        </button>
        <button
          type="button"
          className={`${styles.item} ${sessionsOpen ? styles.active : ''}`}
          onClick={onToggleSessions}
          aria-label={sessionsOpen ? 'Hide sessions' : 'Show sessions'}
          aria-pressed={sessionsOpen}
        >
          <RailIcon name="sessions" />
          <span className={styles.tooltip}>Sessions</span>
        </button>
        <button type="button" className={styles.item} onClick={onOpenInspector} aria-label="Open agent inspector">
          <RailIcon name="inspector" />
          <span className={styles.tooltip}>Inspector</span>
        </button>
        <button type="button" className={styles.item} onClick={onOpenShowcase} aria-label="Open showcase mode">
          <RailIcon name="showcase" />
          <span className={styles.tooltip}>Showcase</span>
        </button>
      </div>
      <div className={styles.bottom}>
        <ThemeSwitcher compact />
      </div>
    </nav>
  )
}
