import { type KeyboardEvent, type ReactNode } from 'react'

import { cn } from '@/lib/cn'

export interface SegmentedOption<T extends string> {
  value: T
  label: ReactNode
  disabled?: boolean
}

interface SegmentedControlProps<T extends string> {
  value: T
  onValueChange: (value: T) => void
  options: readonly SegmentedOption<T>[]
  /** Accessible name for the group. */
  label: string
  className?: string
}

/**
 * Single choice from a small set (a WAI-ARIA radio group styled as a segmented
 * control). Use for settings and ranges; use Tabs when switching content panels.
 */
export function SegmentedControl<T extends string>({
  value,
  onValueChange,
  options,
  label,
  className,
}: SegmentedControlProps<T>) {
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key]
    if (step === undefined) return
    event.preventDefault()
    const enabled = options.filter((option) => !option.disabled)
    const index = enabled.findIndex((option) => option.value === value)
    const next = enabled[(index + step + enabled.length) % enabled.length]
    if (!next) return
    onValueChange(next.value)
    const group = event.currentTarget.parentElement
    group?.querySelector<HTMLButtonElement>(`[data-value="${next.value}"]`)?.focus()
  }

  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn(
        'inline-flex items-center gap-0.5 rounded-lg border border-border bg-surface-muted p-0.5',
        className,
      )}
    >
      {options.map((option) => {
        const selected = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected ? 0 : -1}
            disabled={option.disabled}
            data-value={option.value}
            onKeyDown={onKeyDown}
            onClick={() => {
              onValueChange(option.value)
            }}
            className={cn(
              'inline-flex h-7 items-center justify-center gap-1.5 rounded-md px-2.5 text-[0.8125rem] font-medium whitespace-nowrap transition-colors duration-150 disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-3.5',
              selected
                ? 'bg-surface-raised text-fg shadow-sm ring-1 ring-border'
                : 'text-fg-muted hover:text-fg',
            )}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
