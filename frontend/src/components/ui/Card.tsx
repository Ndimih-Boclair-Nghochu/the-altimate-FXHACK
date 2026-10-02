import { type ComponentProps, type ReactNode } from 'react'

import { cn } from '@/lib/cn'

export function Card({ className, ...props }: ComponentProps<'section'>) {
  return (
    <section
      className={cn('rounded-xl border border-border bg-surface shadow-card', className)}
      {...props}
    />
  )
}

interface CardHeaderProps extends Omit<ComponentProps<'div'>, 'title'> {
  title: ReactNode
  description?: ReactNode
  /** Right-aligned controls (tabs, buttons, badges). */
  actions?: ReactNode
  /** Heading level for the title (default h2). */
  as?: 'h2' | 'h3'
}

export function CardHeader({
  title,
  description,
  actions,
  as: Heading = 'h2',
  className,
  ...props
}: CardHeaderProps) {
  return (
    <div
      className={cn('flex flex-wrap items-start justify-between gap-3 px-5 pt-4 pb-3', className)}
      {...props}
    >
      <div className="min-w-0 space-y-0.5">
        <Heading className="text-sm font-semibold tracking-tight text-fg">{title}</Heading>
        {description ? <p className="text-[0.8125rem] text-fg-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  )
}

export function CardBody({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('px-5 pb-5', className)} {...props} />
}

export function CardFooter({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      className={cn('flex items-center gap-3 border-t border-border px-5 py-3', className)}
      {...props}
    />
  )
}
