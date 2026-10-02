import { type ComponentProps, useId } from 'react'

import { cn } from '@/lib/cn'

export interface SwitchProps extends Omit<
  ComponentProps<'button'>,
  'onChange' | 'role' | 'aria-checked' | 'value'
> {
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  /** Visible label. Omit only if you pass `aria-label`. */
  label?: string
  description?: string
}

/** Accessible on/off toggle (role="switch"). */
export function Switch({
  checked,
  onCheckedChange,
  label,
  description,
  disabled,
  className,
  id,
  ...props
}: SwitchProps) {
  const autoId = useId()
  const switchId = id ?? autoId
  const descriptionId = description ? `${switchId}-description` : undefined

  const control = (
    <button
      id={switchId}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-describedby={descriptionId}
      disabled={disabled}
      onClick={() => {
        onCheckedChange(!checked)
      }}
      className={cn(
        'relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border border-transparent transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50',
        checked ? 'bg-accent-solid' : 'bg-border-strong',
        !label && className,
      )}
      {...props}
    >
      <span
        aria-hidden="true"
        className={cn(
          'pointer-events-none block size-4 rounded-full bg-white shadow-sm transition-transform duration-150 ease-out',
          checked ? 'translate-x-4' : 'translate-x-0.5',
        )}
      />
    </button>
  )

  if (!label) return control

  return (
    <div className={cn('flex items-start justify-between gap-4', className)}>
      <div className="min-w-0 space-y-0.5">
        <label htmlFor={switchId} className="text-sm font-medium text-fg">
          {label}
        </label>
        {description ? (
          <p id={descriptionId} className="text-[0.8125rem] text-fg-muted">
            {description}
          </p>
        ) : null}
      </div>
      {control}
    </div>
  )
}
