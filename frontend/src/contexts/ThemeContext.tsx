import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

export type ThemeMode = 'dark' | 'light' | 'system'
export type ResolvedTheme = 'dark' | 'light'

export const THEME_STORAGE_KEY = 'acp-theme'

interface ThemeContextValue {
  theme: ThemeMode
  resolvedTheme: ResolvedTheme
  setTheme: (theme: ThemeMode) => void
  toggleTheme: () => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function systemTheme(): ResolvedTheme {
  if (typeof window === 'undefined') return 'dark'
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

function readStoredTheme(): ThemeMode {
  if (typeof window === 'undefined') return 'system'
  // 支持 ?theme=light|dark 便于截图、分享与验收，不写回 localStorage
  const query = new URLSearchParams(window.location.search).get('theme')
  if (query === 'dark' || query === 'light' || query === 'system') return query
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY)
    if (value === 'dark' || value === 'light' || value === 'system') return value
  } catch {
    // 隐私模式下 localStorage 不可读，退回系统偏好
  }
  return 'system'
}

/** 把主题类挂到 <html>；同时供 index.html 的 FOUC 内联脚本调用（逻辑需保持一致） */
export function applyThemeClass(resolved: ResolvedTheme) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.classList.remove('dark', 'light')
  root.classList.add(resolved)
  root.dataset.theme = resolved
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeMode>(readStoredTheme)
  const [systemResolved, setSystemResolved] = useState<ResolvedTheme>(systemTheme)

  const resolvedTheme = theme === 'system' ? systemResolved : theme

  useEffect(() => {
    const query = window.matchMedia('(prefers-color-scheme: light)')
    const onChange = (event: MediaQueryListEvent) => {
      setSystemResolved(event.matches ? 'light' : 'dark')
    }
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  useEffect(() => {
    applyThemeClass(resolvedTheme)
  }, [resolvedTheme])

  const setTheme = useCallback((next: ThemeMode) => {
    setThemeState(next)
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next)
    } catch {
      // 忽略写入失败，主题仍在本次会话生效
    }
  }, [])

  const toggleTheme = useCallback(() => {
    setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')
  }, [resolvedTheme, setTheme])

  const value = useMemo<ThemeContextValue>(
    () => ({ theme, resolvedTheme, setTheme, toggleTheme }),
    [theme, resolvedTheme, setTheme, toggleTheme],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext)
  if (!context) throw new Error('useTheme 必须在 ThemeProvider 内使用')
  return context
}
