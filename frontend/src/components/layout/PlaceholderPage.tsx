import { Check, type LucideIcon } from 'lucide-react'
import { type ReactNode } from 'react'

import { Badge, Card, EmptyState } from '@/components/ui'

import { PageHeader } from './PageHeader'

interface PlaceholderPageProps {
  title: string
  description: string
  icon: LucideIcon
  emptyTitle: string
  emptyDescription: string
  /** What this page will show once built. */
  planned: readonly string[]
  /** Extra content rendered above the placeholder card. */
  children?: ReactNode
}

/** Consistent "coming in Stage 6" page used until each view is wired to real data. */
export function PlaceholderPage({
  title,
  description,
  icon,
  emptyTitle,
  emptyDescription,
  planned,
  children,
}: PlaceholderPageProps) {
  return (
    <>
      <PageHeader
        title={title}
        description={description}
        badge={<Badge variant="neutral">Stage 6</Badge>}
      />
      <div className="space-y-6">
        {children}
        <Card>
          <EmptyState icon={icon} title={emptyTitle} description={emptyDescription}>
            <ul
              className="grid w-full max-w-lg gap-2 text-left sm:grid-cols-2"
              aria-label="Planned"
            >
              {planned.map((item) => (
                <li
                  key={item}
                  className="flex items-start gap-2 rounded-lg border border-border bg-surface-muted/50 px-3 py-2 text-[0.8125rem] text-fg-muted"
                >
                  <Check className="mt-0.5 size-3.5 shrink-0 text-fg-subtle" aria-hidden="true" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </EmptyState>
        </Card>
      </div>
    </>
  )
}
