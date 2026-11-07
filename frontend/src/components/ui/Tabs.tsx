import type { ReactNode } from 'react'
import { cn } from '../../utils'

export interface TabItem<T extends string = string> {
  key: T
  label: string
  icon?: ReactNode
}

export interface TabsProps<T extends string = string> {
  items: TabItem<T>[]
  value: T
  onChange: (key: T) => void
  variant?: 'pill' | 'underline'
  className?: string
}

export function Tabs<T extends string = string>({
  items,
  value,
  onChange,
  variant = 'pill',
  className,
}: TabsProps<T>) {
  if (variant === 'underline') {
    return (
      <div role="tablist" className={cn('flex items-center gap-6 border-b border-line/70', className)}>
        {items.map((item) => {
          const active = item.key === value
          return (
            <button
              key={item.key}
              role="tab"
              aria-selected={active}
              onClick={() => onChange(item.key)}
              className={cn(
                'relative -mb-px flex items-center gap-2 border-b-2 px-1 pb-3 pt-1 text-sm transition-colors',
                active
                  ? 'border-brand text-ink'
                  : 'border-transparent text-ink-subtle hover:text-ink-muted',
              )}
            >
              {item.icon}
              {item.label}
            </button>
          )
        })}
      </div>
    )
  }

  return (
    <div role="tablist" className={cn('inline-flex items-center gap-1 rounded-pill border border-line/70 bg-panel-2/50 p-1', className)}>
      {items.map((item) => {
        const active = item.key === value
        return (
          <button
            key={item.key}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(item.key)}
            className={cn(
              'flex items-center gap-2 rounded-pill px-4 py-2 text-sm transition-all duration-200',
              active
                ? 'bg-brand text-brand-fg shadow-glow'
                : 'text-ink-muted hover:bg-panel-3/70 hover:text-ink',
            )}
          >
            {item.icon}
            {item.label}
          </button>
        )
      })}
    </div>
  )
}
