import { cn } from '../../utils'

export interface SkeletonProps {
  variant?: 'text' | 'card' | 'table' | 'stat'
  lines?: number
  className?: string
}

export function Skeleton({ variant = 'text', lines = 3, className }: SkeletonProps) {
  const block = 'animate-pulse rounded-lg bg-panel-3/80'

  if (variant === 'stat') {
    return (
      <div className={cn('glass rounded-card p-5', className)}>
        <div className={cn(block, 'h-3 w-20')} />
        <div className={cn(block, 'mt-5 h-9 w-28')} />
        <div className={cn(block, 'mt-4 h-3 w-36')} />
      </div>
    )
  }

  if (variant === 'card') {
    return (
      <div className={cn('glass rounded-card p-5', className)}>
        <div className={cn(block, 'h-4 w-1/3')} />
        <div className={cn(block, 'mt-4 h-3 w-full')} />
        <div className={cn(block, 'mt-2 h-3 w-5/6')} />
        <div className={cn(block, 'mt-2 h-3 w-2/3')} />
      </div>
    )
  }

  if (variant === 'table') {
    return (
      <div className={cn('space-y-2', className)}>
        {Array.from({ length: lines }).map((_, index) => (
          <div key={index} className={cn(block, 'h-10 w-full')} />
        ))}
      </div>
    )
  }

  return (
    <div className={cn('space-y-2', className)}>
      {Array.from({ length: lines }).map((_, index) => (
        <div key={index} className={cn(block, 'h-3', index === lines - 1 ? 'w-2/3' : 'w-full')} />
      ))}
    </div>
  )
}
