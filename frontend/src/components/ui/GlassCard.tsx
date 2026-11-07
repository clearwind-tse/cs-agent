import type { ReactNode } from 'react'
import { motion } from 'framer-motion'
import { cn } from '../../utils'

export interface GlassCardProps {
  children?: ReactNode
  className?: string
  tone?: 'default' | 'raised' | 'sunken'
  interactive?: boolean
  glow?: boolean
}

const TONES: Record<NonNullable<GlassCardProps['tone']>, string> = {
  default: 'glass',
  raised: 'glass !bg-panel-2/80',
  sunken: 'border border-line/60 bg-canvas/45',
}

export function GlassCard({
  children,
  className,
  tone = 'default',
  interactive = false,
  glow = false,
}: GlassCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
      whileHover={interactive ? { y: -3 } : undefined}
      className={cn(
        'relative rounded-card',
        TONES[tone],
        glow && 'shadow-glow',
        interactive && 'transition-shadow hover:shadow-glow',
        className,
      )}
    >
      {children}
    </motion.div>
  )
}
