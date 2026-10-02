import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react'
import { type ReactNode } from 'react'

import { cn } from '@/lib/cn'
import { directionOf, formatNumber } from '@/lib/format'

import { Skeleton } from './Skeleton'

export interface StatProps {
  label: string
  /** Pre-formatted value. `null` renders an em dash (no data). */
  value: ReactNode
  /** Signed change; sign, icon and colour are derived from it. */
  delta?: number | null
  /** Formats the delta magnitude, e.g. `(v) => formatPercent(v, { signed: true })`. */
  formatDelta?: (value: number) => string
  /** Context for the delta, e.g. "today" or "vs last week". */
  deltaLabel?: string
  /** Set when a rise is bad (e.g. drawdown), so colours invert but signs don't. */
  invertDeltaColor?: boolean
  hint?: ReactNode
  loading?: boolean
  className?: string
}

const DIRECTION_TEXT = { up: 'Up', down: 'Down', flat: 'Unchanged' } as const

export function Stat({
  label,
  value,
  delta,
  formatDelta = (v) => formatNumber(v, { signed: true }),
  deltaLabel,
  invertDeltaColor = false,
  hint,
  loading = false,
  className,
}: StatProps) {
  const direction = typeof delta === 'number' ? directionOf(delta) : null
  const good = direction === 'flat' ? null : (direction === 'up') !== invertDeltaColor
  const DeltaIcon =
    direction === 'up' ? ArrowUpRight : direction === 'down' ? ArrowDownRight : Minus

  return (
    <dl className={cn('flex min-w-0 flex-col gap-1.5', className)}>
      <dt className="truncate text-[0.8125rem] font-medium text-fg-muted">{label}</dt>
      <dd className="flex min-w-0 flex-col gap-1.5">
        {loading ? (
          <>
            <Skeleton className="h-7 w-28" />
            <span className="sr-only">Loading</span>
          </>
        ) : (
          <span className="truncate text-2xl leading-7 font-semibold tracking-tight text-fg tabular-nums">
            {value ?? <span className="text-fg-subtle">—</span>}
          </span>
        )}
        {loading && delta !== undefined ? (
          <Skeleton className="h-4 w-20" />
        ) : direction !== null && typeof delta === 'number' ? (
          <span
            className={cn(
              'inline-flex items-center gap-1 text-xs font-medium tabular-nums',
              good === null ? 'text-fg-muted' : good ? 'text-profit' : 'text-loss',
            )}
            data-direction={direction}
          >
            <DeltaIcon className="size-3.5" aria-hidden="true" />
            <span className="sr-only">{DIRECTION_TEXT[direction]}</span>
            <span>{formatDelta(delta)}</span>
            {deltaLabel ? <span className="font-normal text-fg-muted">{deltaLabel}</span> : null}
          </span>
        ) : null}
        {hint ? <span className="truncate text-xs text-fg-muted">{hint}</span> : null}
      </dd>
    </dl>
  )
}
