import { cn } from '../../utils'

export interface AuroraBackgroundProps {
  variant?: 'default' | 'subtle' | 'login'
  className?: string
}

interface Orb {
  color: string
  size: number
  x: string
  y: string
  delay: string
  duration: string
  slow?: boolean
}

const ORBS: Orb[] = [
  { color: 'rgb(var(--c-mint) / 0.85)', size: 460, x: '-8%', y: '-18%', delay: '0s', duration: '30s' },
  { color: 'rgb(var(--c-iris) / 0.9)', size: 520, x: '42%', y: '-26%', delay: '-8s', duration: '36s', slow: true },
  { color: 'rgb(var(--c-flare) / 0.75)', size: 420, x: '72%', y: '18%', delay: '-16s', duration: '32s' },
  { color: 'rgb(var(--c-iris) / 0.5)', size: 340, x: '8%', y: '58%', delay: '-24s', duration: '40s', slow: true },
]

/**
 * 极光氛围层：纯 CSS 光晕 + 网格 + 发丝渐变，零图片、零网络请求、零 JS 动画循环。
 * 明暗主题的浓度由 tokens.css 的 --orb-opacity / --grid-opacity 控制。
 */
export function AuroraBackground({ variant = 'default', className }: AuroraBackgroundProps) {
  const scale = variant === 'subtle' ? 0.82 : variant === 'login' ? 1.15 : 1

  return (
    <div
      aria-hidden="true"
      className={cn('pointer-events-none absolute inset-0 overflow-hidden', className)}
    >
      <div className="aurora-grid absolute inset-0" />

      {ORBS.map((orb, index) => (
        <div
          key={index}
          className={cn('aurora-orb', orb.slow && 'aurora-orb-slow')}
          style={{
            width: orb.size * scale,
            height: orb.size * scale,
            left: orb.x,
            top: orb.y,
            background: orb.color,
            animationDelay: orb.delay,
            animationDuration: orb.duration,
          }}
        />
      ))}

      <div
        className="aurora-hairline absolute left-0 right-0 top-0 h-px opacity-70"
        style={{ animation: 'auroraShimmer 6s ease-in-out infinite' }}
      />
      <div className="absolute inset-0 bg-canvas/10" />
    </div>
  )
}
