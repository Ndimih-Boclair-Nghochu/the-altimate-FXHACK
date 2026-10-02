import { LoaderCircle } from 'lucide-react'
import { type ComponentProps } from 'react'

import { type ButtonSize, type ButtonVariant, buttonClasses } from './buttonStyles'

export interface ButtonProps extends ComponentProps<'button'> {
  variant?: ButtonVariant
  size?: ButtonSize
  /** Shows a spinner, disables the button and sets aria-busy. */
  loading?: boolean
}

export function Button({
  variant = 'secondary',
  size = 'md',
  loading = false,
  disabled,
  className,
  children,
  type = 'button',
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={Boolean(disabled) || loading}
      aria-busy={loading || undefined}
      className={buttonClasses({ variant, size, className })}
      {...props}
    >
      {loading ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : null}
      {children}
    </button>
  )
}
