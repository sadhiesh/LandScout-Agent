import { useEffect, useRef, useState } from 'react'
import { THEMES, useTheme } from './ThemeContext'
import styles from './ThemeSwitcher.module.css'

interface ThemeSwitcherProps {
  compact?: boolean
}

export default function ThemeSwitcher({ compact = false }: ThemeSwitcherProps) {
  const { theme, setTheme } = useTheme()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const active = THEMES.find((t) => t.id === theme)

  return (
    <div className={`${styles.wrap} ${compact ? styles.compact : ''}`} ref={ref}>
      <button
        type="button"
        className={styles.trigger}
        onClick={() => setOpen((v) => !v)}
        title={`Theme: ${active?.label ?? 'Ocean'}`}
        aria-label={`Change theme. Current theme: ${active?.label ?? 'Ocean'}`}
        aria-expanded={open}
        aria-controls="theme-options"
      >
        <span aria-hidden>◐</span>
        <span className={styles.dot} style={{ background: active?.swatch }} />
        {!compact && active?.label}
      </button>

      {open && (
        <div className={styles.popover} id="theme-options" aria-label="Choose a theme">
          <div className={styles.popoverTitle}>Appearance</div>
          {THEMES.map((t) => (
            <button
              key={t.id}
              type="button"
              aria-pressed={t.id === theme}
              className={`${styles.option} ${t.id === theme ? styles.optionActive : ''}`}
              onClick={() => {
                setTheme(t.id)
                setOpen(false)
              }}
            >
              <span
                className={styles.dot}
                style={{ background: t.swatch }}
              />
              <span className={styles.optionText}>
                <span className={styles.optionLabel}>{t.label}</span>
                <span className={styles.optionHint}>{t.hint}</span>
              </span>
              {t.id === theme && <span className={styles.check}>✓</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
