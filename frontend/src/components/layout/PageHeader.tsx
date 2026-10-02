import { type ReactNode } from 'react'

import { cn } from '@/lib/cn'

interface PageHeaderProps {
  title: string
  description?: ReactNode
  /** Inline status next to the title (e.g. a "Stage 6" badge). */
  badge?: ReactNode
  /** Right-aligned page actions. */
  actions?: ReactNode
  className?: string
}

export function PageHeader({ title, description, badge, actions, className }: PageHeaderProps) {
  return (
    <>
      <title>{`${title} · Altimate FX`}</title>
      <div className={cn('mb-6 flex flex-wrap items-end justify-between gap-4', className)}>
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-xl font-semibold tracking-tight text-fg sm:text-2xl">{title}</h1>
            {badge}
          </div>
          {description ? <p className="max-w-2xl text-sm text-fg-muted">{description}</p> : null}
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
      </div>
    </>
  )
}
