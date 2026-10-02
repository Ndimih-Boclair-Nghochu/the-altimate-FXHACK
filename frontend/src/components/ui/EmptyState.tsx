import { type LucideIcon } from 'lucide-react'
import { type ReactNode } from 'react'

import { cn } from '@/lib/cn'

interface EmptyStateProps {
  icon: LucideIcon
  title: string
  description?: ReactNode
  /** Optional actions or supplementary content below the description. */
  children?: ReactNode
  className?: string
}

/** Calm placeholder for "nothing here yet" — explains what will appear and why. */
export function EmptyState({
  icon: Icon,
  title,
  description,
  children,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center px-6 py-12 text-center sm:py-16',
        className,
      )}
    >
      <div className="relative mb-4">
        <div aria-hidden="true" className="absolute -inset-3 rounded-2xl bg-accent/10 blur-xl" />
        <div className="relative flex size-11 items-center justify-center rounded-xl border border-border-strong bg-surface-raised text-fg-muted shadow-card">
          <Icon className="size-5" aria-hidden="true" />
        </div>
      </div>
      <h3 className="text-sm font-semibold text-fg">{title}</h3>
      {description ? (
        <p className="mt-1.5 max-w-md text-sm leading-relaxed text-fg-muted">{description}</p>
      ) : null}
      {children ? <div className="mt-5 flex flex-wrap justify-center gap-2">{children}</div> : null}
    </div>
  )
}
