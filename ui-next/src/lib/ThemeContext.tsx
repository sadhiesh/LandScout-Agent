import { createContext, useCallback, useContext, useEffect, useRef, useState, ReactNode } from 'react'

export type Theme = 'ocean' | 'daylight' | 'midnight' | 'terra' | 'command'

export interface ThemeMeta {
  id: Theme
  label: string
  hint: string
  swatch: string
}

export const THEMES: ThemeMeta[] = [
  { id: 'ocean', label: 'Ocean', hint: 'Clear blue investor workspace', swatch: 'var(--theme-ocean-swatch)' },
  { id: 'daylight', label: 'Daylight', hint: 'Crisp neutral daylight', swatch: 'var(--theme-daylight-swatch)' },
  { id: 'midnight', label: 'Midnight', hint: 'Lifted navy for low light', swatch: 'var(--theme-midnight-swatch)' },
  { id: 'terra', label: 'Terra', hint: 'Grounded earth tones', swatch: 'var(--theme-terra-swatch)' },
  { id: 'command', label: 'Command', hint: 'Technical, reduced glare', swatch: 'var(--theme-command-swatch)' },
]

const STORAGE_KEY = 'landscout-next-theme'
const MANUAL_KEY = 'landscout-next-theme-manual'
const DEFAULT_THEME: Theme = 'ocean'

interface ThemeContextType {
  theme: Theme
  setTheme: (theme: Theme) => void
  /** Auto-switch to a theme (e.g. entering Showcase Mode) without overriding a user's explicit choice. */
  suggestTheme: (theme: Theme) => void
  /** Restore whatever theme was active before the last suggestTheme() call. */
  restoreSuggested: () => void
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined)

function isTheme(value: string | null): value is Theme {
  return value === 'ocean' || value === 'daylight' || value === 'midnight' || value === 'terra' || value === 'command'
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    return isTheme(stored) ? stored : DEFAULT_THEME
  })
  const manualRef = useRef(localStorage.getItem(MANUAL_KEY) === '1')
  const preSuggestRef = useRef<Theme | null>(null)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, theme)
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  const setTheme = useCallback((next: Theme) => {
    manualRef.current = true
    localStorage.setItem(MANUAL_KEY, '1')
    setThemeState(next)
  }, [])

  const suggestTheme = useCallback((next: Theme) => {
    if (manualRef.current) return
    preSuggestRef.current = theme
    setThemeState(next)
  }, [theme])

  const restoreSuggested = useCallback(() => {
    if (manualRef.current) return
    if (preSuggestRef.current) {
      setThemeState(preSuggestRef.current)
      preSuggestRef.current = null
    }
  }, [])

  return (
    <ThemeContext.Provider value={{ theme, setTheme, suggestTheme, restoreSuggested }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (!context) {
    throw new Error('useTheme must be used within ThemeProvider')
  }
  return context
}
