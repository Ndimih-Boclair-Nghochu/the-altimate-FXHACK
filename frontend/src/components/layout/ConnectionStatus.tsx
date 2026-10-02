import { CircleCheck, LoaderCircle, TriangleAlert, Unplug } from 'lucide-react'

import { Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'

import { type ConnectionState } from './connection'

const META = {
  connecting: { label: 'Connecting', icon: LoaderCircle, tone: 'text-fg-muted', spin: true },
  connected: { label: 'Connected', icon: CircleCheck, tone: 'text-profit', spin: false },
  degraded: { label: 'Degraded', icon: TriangleAlert, tone: 'text-warning', spin: false },
  offline: { label: 'Offline', icon: Unplug, tone: 'text-loss', spin: false },
} as const

interface ConnectionStatusProps {
  state: ConnectionState
  /** Backend version, when known. */
  version?: string
  /** Error message from the last failed check. */
  error?: string
  /** Re-check now. */
  onRetry?: () => void
}

/** Backend connectivity, shown by icon shape + label (never colour alone). */
export function ConnectionStatus({ state, version, error, onRetry }: ConnectionStatusProps) {
  const { label, icon: Icon, tone, spin } = META[state]
  const detail =
    state === 'connected' || state === 'degraded'
      ? `Backend API${version ? ` v${version}` : ''} · click to re-check`
      : state === 'offline'
        ? `${error ?? 'Backend unreachable'} · click to retry`
        : 'Checking backend health…'

  return (
    <Tooltip content={detail} side="bottom" align="end">
      <button
        type="button"
        onClick={onRetry}
        data-state={state}
        className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-xs font-medium text-fg-muted transition-colors hover:bg-surface-muted hover:text-fg"
      >
        <Icon className={cn('size-4', tone, spin && 'animate-spin')} aria-hidden="true" />
        <span className="sr-only">Backend status: </span>
        <span className="max-sm:sr-only">{label}</span>
      </button>
    </Tooltip>
  )
}
