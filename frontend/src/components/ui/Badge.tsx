import type { ReactNode } from 'react'
import { cn } from '../../utils'

export interface BadgeProps {
  children?: ReactNode
  tone?: 'mint' | 'flare' | 'iris' | 'ok' | 'warn' | 'bad' | 'neutral'
  dot?: boolean
  size?: 'sm' | 'md'
  className?: string
}

const TONES: Record<NonNullable<BadgeProps['tone']>, { wrap: string; dot: string }> = {
  mint: { wrap: 'border-mint/35 bg-mint/10 text-ok', dot: 'bg-mint' },
  flare: { wrap: 'border-flare/35 bg-flare/10 text-flare', dot: 'bg-flare' },
  iris: { wrap: 'border-iris/35 bg-iris/10 text-info', dot: 'bg-iris' },
  ok: { wrap: 'border-ok/35 bg-ok/10 text-ok', dot: 'bg-ok' },
  warn: { wrap: 'border-warn/35 bg-warn/10 text-warn', dot: 'bg-warn' },
  bad: { wrap: 'border-bad/35 bg-bad/10 text-bad', dot: 'bg-bad' },
  neutral: { wrap: 'border-line bg-panel-2/60 text-ink-muted', dot: 'bg-ink-subtle' },
}

export function Badge({ children, tone = 'neutral', dot = false, size = 'md', className }: BadgeProps) {
  const palette = TONES[tone]
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-pill border font-mono font-medium uppercase tracking-widest',
        size === 'sm' ? 'px-2 py-0.5 text-[10px]' : 'px-2.5 py-1 text-[11px]',
        palette.wrap,
        className,
      )}
    >
      {dot && <span className={cn('h-1.5 w-1.5 rounded-full', palette.dot)} />}
      {children}
    </span>
  )
}
