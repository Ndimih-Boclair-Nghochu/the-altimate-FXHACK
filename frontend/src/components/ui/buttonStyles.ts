import { cn } from '@/lib/cn'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'danger-subtle'
export type ButtonSize = 'sm' | 'md' | 'lg' | 'icon' | 'icon-sm'

const base =
  'inline-flex shrink-0 select-none items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium transition-[background-color,border-color,color,box-shadow] duration-150 disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0'

const variants: Record<ButtonVariant, string> = {
  primary: 'bg-accent-solid text-on-accent hover:bg-accent-solid-hover',
  secondary:
    'border border-border bg-surface-raised text-fg shadow-card hover:border-border-strong hover:bg-surface-muted',
  ghost: 'text-fg-muted hover:bg-surface-muted hover:text-fg',
  danger: 'bg-loss-solid text-white hover:bg-loss-solid-hover',
  'danger-subtle':
    'border border-loss/35 bg-loss/10 text-loss hover:border-loss/60 hover:bg-loss/15',
}

const sizes: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-[0.8125rem]',
  md: 'h-9 px-3.5',
  lg: 'h-10 px-4',
  icon: 'size-9',
  'icon-sm': 'size-8',
}

/** Button classes, for links or other elements that should look like a button. */
export function buttonClasses({
  variant = 'secondary',
  size = 'md',
  className,
}: { variant?: ButtonVariant; size?: ButtonSize; className?: string } = {}) {
  return cn(base, variants[variant], sizes[size], className)
}
