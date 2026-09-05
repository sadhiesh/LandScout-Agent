import styles from './LandScoutLogo.module.css'

interface LandScoutLogoProps {
  compact?: boolean
  className?: string
}

export default function LandScoutLogo({ compact = false, className = '' }: LandScoutLogoProps) {
  return (
    <div className={`${styles.logo} ${compact ? styles.compact : ''} ${className}`.trim()}>
      <span className={styles.mark} aria-hidden="true">
        <svg viewBox="0 0 64 64" focusable="false">
          <defs>
            <linearGradient id="landscout-sky" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="var(--accent-hover)" />
              <stop offset="100%" stopColor="var(--accent-primary)" />
            </linearGradient>
            <linearGradient id="landscout-field" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="var(--accent-secondary)" />
              <stop offset="100%" stopColor="var(--success)" />
            </linearGradient>
          </defs>

          <rect x="6" y="6" width="52" height="52" rx="16" className={styles.frame} />
          <circle cx="45" cy="19" r="5" className={styles.sun} />
          <path d="M15 39 28 24l9 10 7-8 6 13Z" fill="url(#landscout-sky)" className={styles.mountain} />
          <path d="M12 43c8-9 20-11 30-6 6 3 10 4 16 2v13H12Z" fill="url(#landscout-field)" className={styles.fieldBack} />
          <path d="M10 49c11-5 22-5 33 0 6 2 11 2 15 1v8H10Z" className={styles.fieldFront} />
          <path
            d="M26 44c2 0 5 1 8 3 4 2 7 4 10 4 2 0 5-1 8-3"
            className={styles.road}
          />
          <path d="M22 40h11l-5.5-6.5Z" className={styles.roof} />
          <path d="M24 40h7v8h-7Z" className={styles.home} />
        </svg>
      </span>

      {!compact && (
        <span className={styles.wordmark}>
          <strong>LandScout</strong>
          <span>Investor console</span>
        </span>
      )}
    </div>
  )
}
