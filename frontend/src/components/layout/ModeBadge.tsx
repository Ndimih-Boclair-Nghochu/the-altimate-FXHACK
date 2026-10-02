import { Badge, type BadgeVariant } from '@/components/ui'
import { type TradingMode } from '@/lib/api'
import { cn } from '@/lib/cn'

const MODE_META: Record<TradingMode, { label: string; variant: BadgeVariant; hint: string }> = {
  paper: {
    label: 'Paper',
    variant: 'neutral',
    hint: 'Paper trading: fills are simulated locally, no money at risk.',
  },
  practice: {
    label: 'Practice',
    variant: 'accent',
    hint: 'Practice account: broker demo environment, no real money at risk.',
  },
  live: {
    label: 'Live',
    variant: 'danger-solid',
    hint: 'Live trading: orders use real money.',
  },
}

interface ModeBadgeProps {
  /** Mode reported by the backend; undefined while unknown (loading or offline). */
  mode: TradingMode | undefined
  className?: string
}

/** Always-visible trading mode. LIVE is red with a pulsing dot so it can't be missed. */
export function ModeBadge({ mode, className }: ModeBadgeProps) {
  const classes = cn('h-6 px-2 text-2xs font-semibold tracking-[0.08em] uppercase', className)

  if (!mode) {
    return (
      <Badge variant="neutral" className={cn(classes, 'text-fg-subtle')} data-mode="unknown">
        <span className="sr-only">Trading mode: </span>
        <span aria-hidden="true">Mode</span>
        <span aria-hidden="true">—</span>
        <span className="sr-only">unknown</span>
      </Badge>
    )
  }

  const meta = MODE_META[mode]
  return (
    <Badge
      variant={meta.variant}
      dot
      pulse={mode === 'live'}
      className={classes}
      data-mode={mode}
      title={meta.hint}
    >
      <span className="sr-only">Trading mode: </span>
      <span>{meta.label}</span>
    </Badge>
  )
}
