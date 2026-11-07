import { Monitor, Moon, Sun } from 'lucide-react'
import { useTheme, type ThemeMode } from '../../contexts/ThemeContext'
import { cn } from '../../utils'

export interface ThemeToggleProps {
  compact?: boolean
  showLabel?: boolean
  className?: string
}

const OPTIONS: { key: ThemeMode; label: string; icon: typeof Sun }[] = [
  { key: 'dark', label: '暗色', icon: Moon },
  { key: 'light', label: '亮色', icon: Sun },
  { key: 'system', label: '跟随系统', icon: Monitor },
]

export function ThemeToggle({ compact = false, showLabel = false, className }: ThemeToggleProps) {
  const { theme, setTheme } = useTheme()

  return (
    <div
      role="group"
      aria-label="主题模式"
      className={cn(
        'inline-flex items-center gap-0.5 rounded-pill border border-line/70 bg-panel-2/60 p-1 backdrop-blur-xl',
        className,
      )}
    >
      {OPTIONS.map(({ key, label, icon: Icon }) => {
        const active = theme === key
        return (
          <button
            key={key}
            type="button"
            aria-pressed={active}
            aria-label={label}
            title={label}
            onClick={() => setTheme(key)}
            className={cn(
              'flex items-center justify-center gap-1.5 rounded-pill transition-all duration-200',
              compact ? 'h-7 w-7' : 'h-8 px-3',
              active
                ? 'bg-brand text-brand-fg shadow-glow'
                : 'text-ink-subtle hover:bg-panel-3/70 hover:text-ink',
            )}
          >
            <Icon size={compact ? 14 : 15} strokeWidth={1.8} />
            {showLabel && <span className="text-xs font-medium">{label}</span>}
          </button>
        )
      })}
    </div>
  )
}
