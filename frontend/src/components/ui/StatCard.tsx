import type { ReactNode } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import { cn } from '../../utils'

export interface StatCardProps {
  label: string
  value: ReactNode
  delta?: string
  deltaTone?: 'up' | 'down' | 'flat'
  icon?: ReactNode
  hint?: string
  tone?: 'mint' | 'flare' | 'iris' | 'neutral'
  chart?: ReactNode
  className?: string
}

const ACCENTS: Record<NonNullable<StatCardProps['tone']>, string> = {
  mint: 'text-ok',
  flare: 'text-flare',
  iris: 'text-info',
  neutral: 'text-ink-muted',
}

export function StatCard({
  label,
  value,
  delta,
  deltaTone = 'flat',
  icon,
  hint,
  tone = 'neutral',
  chart,
  className,
}: StatCardProps) {
  const reduce = useReducedMotion()

  return (
    <motion.div
      variants={{
        hidden: { opacity: 0, y: reduce ? 0 : 14 },
        show: { opacity: 1, y: 0 },
      }}
      whileHover={reduce ? undefined : { y: -3 }}
      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      className={cn('glass group relative overflow-hidden rounded-card p-5', className)}
    >
      <div className="aurora-hairline absolute left-5 right-5 top-0 h-px opacity-0 transition-opacity duration-300 group-hover:opacity-100" />

      <div className="flex items-start justify-between gap-3">
        <span className="text-xs font-medium tracking-[0.06em] text-ink-muted">{label}</span>
        {icon && <span className={cn('shrink-0', ACCENTS[tone])}>{icon}</span>}
      </div>

      <div className="mt-4 flex items-end justify-between gap-3">
        <div className="font-display text-[34px] font-bold leading-none tracking-tight text-ink tabular-nums">
          {value}
        </div>
        {chart && <div className="h-10 w-24 shrink-0 opacity-90">{chart}</div>}
      </div>

      <div className="mt-3 flex items-center gap-2 text-xs">
        {delta && (
          <span
            className={cn(
              'font-mono font-medium',
              deltaTone === 'up' && 'text-ok',
              deltaTone === 'down' && 'text-bad',
              deltaTone === 'flat' && 'text-ink-subtle',
            )}
          >
            {delta}
          </span>
        )}
        {hint && <span className="truncate text-ink-subtle">{hint}</span>}
      </div>
    </motion.div>
  )
}
