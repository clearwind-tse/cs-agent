import { motion, useReducedMotion } from 'framer-motion'
import { cn } from '../../utils'

export interface ProgressProps {
  value: number
  tone?: 'mint' | 'flare' | 'iris' | 'ok' | 'warn' | 'bad'
  showLabel?: boolean
  label?: string
  className?: string
}

const FILLS: Record<NonNullable<ProgressProps['tone']>, string> = {
  mint: 'bg-mint',
  flare: 'bg-flare',
  iris: 'bg-iris',
  ok: 'bg-ok',
  warn: 'bg-warn',
  bad: 'bg-bad',
}

export function Progress({ value, tone = 'mint', showLabel = false, label, className }: ProgressProps) {
  const reduce = useReducedMotion()
  const clamped = Math.max(0, Math.min(100, value))

  return (
    <div className={cn('w-full', className)}>
      {(showLabel || label) && (
        <div className="mb-1.5 flex items-center justify-between text-xs text-ink-muted">
          <span>{label}</span>
          <span className="font-mono tabular-nums text-ink">{Math.round(clamped)}%</span>
        </div>
      )}
      <div
        role="progressbar"
        aria-valuenow={Math.round(clamped)}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-2 w-full overflow-hidden rounded-pill bg-panel-3/80"
      >
        <motion.div
          initial={{ width: reduce ? `${clamped}%` : 0 }}
          animate={{ width: `${clamped}%` }}
          transition={{ duration: reduce ? 0 : 0.9, ease: [0.22, 1, 0.36, 1] }}
          className={cn('h-full rounded-pill', FILLS[tone])}
        />
      </div>
    </div>
  )
}
