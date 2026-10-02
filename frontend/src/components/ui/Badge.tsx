import { type ComponentProps } from 'react'

import { cn } from '@/lib/cn'

export type BadgeVariant = 'neutral' | 'accent' | 'success' | 'danger' | 'danger-solid' | 'warning'

const variants: Record<BadgeVariant, { badge: string; dot: string }> = {
  neutral: { badge: 'border-border-strong bg-surface-muted text-fg-muted', dot: 'bg-fg-muted' },
  accent: { badge: 'border-accent/30 bg-accent/10 text-accent', dot: 'bg-accent' },
  success: { badge: 'border-profit/30 bg-profit/10 text-profit', dot: 'bg-profit' },
  danger: { badge: 'border-loss/40 bg-loss/12 text-loss', dot: 'bg-loss' },
  'danger-solid': { badge: 'border-loss-solid bg-loss-solid text-white', dot: 'bg-white' },
  warning: { badge: 'border-warning/35 bg-warning/10 text-warning', dot: 'bg-warning' },
}

export interface BadgeProps extends ComponentProps<'span'> {
  variant?: BadgeVariant
  /** Leading status dot. */
  dot?: boolean
  /** Animate the dot (reserved for states that need attention, e.g. LIVE). */
  pulse?: boolean
}

export function Badge({
  variant = 'neutral',
  dot = false,
  pulse = false,
  className,
  children,
  ...props
}: BadgeProps) {
  const styles = variants[variant]
  return (
    <span
      className={cn(
        'inline-flex h-6 shrink-0 items-center gap-1.5 rounded-md border px-2 text-xs font-medium whitespace-nowrap',
        styles.badge,
        className,
      )}
      {...props}
    >
      {dot ? (
        <span className="relative flex size-1.5" aria-hidden="true">
          {pulse ? (
            <span
              className={cn('absolute inset-0 animate-ping rounded-full opacity-75', styles.dot)}
            />
          ) : null}
          <span className={cn('relative size-1.5 rounded-full', styles.dot)} />
        </span>
      ) : null}
      {children}
    </span>
  )
}
