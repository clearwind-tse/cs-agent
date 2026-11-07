import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { cn } from '../../utils'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'outline' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  icon?: ReactNode
  leading?: ReactNode
}

const VARIANTS: Record<NonNullable<ButtonProps['variant']>, string> = {
  primary:
    'bg-brand text-brand-fg shadow-glow hover:brightness-110 border border-transparent',
  secondary:
    'glass text-ink hover:border-line-strong hover:bg-panel-2/80 border',
  outline:
    'border border-line-strong text-ink hover:bg-panel-2/60 bg-transparent',
  ghost:
    'text-ink-muted hover:text-ink hover:bg-panel-2/60 border border-transparent',
  danger:
    'bg-bad/15 text-bad border border-bad/40 hover:bg-bad/25',
}

const SIZES: Record<NonNullable<ButtonProps['size']>, string> = {
  sm: 'h-8 px-3 text-xs gap-1.5 rounded-lg',
  md: 'h-10 px-4 text-sm gap-2 rounded-xl',
  lg: 'h-12 px-6 text-sm gap-2.5 rounded-2xl',
}

export function Button({
  variant = 'secondary',
  size = 'md',
  icon,
  leading,
  className,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      type="button"
      className={cn(
        'inline-flex select-none items-center justify-center font-medium tracking-tight',
        'transition-all duration-200 ease-out active:translate-y-0 hover:-translate-y-0.5',
        'disabled:pointer-events-none disabled:opacity-45',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-halo',
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {leading}
      <span>{children}</span>
      {icon}
    </button>
  )
}
