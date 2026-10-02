import { type ReactNode, type RefObject, useId, useRef } from 'react'
import { createPortal } from 'react-dom'

import { useModal } from '@/hooks/useModal'
import { cn } from '@/lib/cn'

export interface DialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  description?: ReactNode
  /** Decorative icon shown beside the title. */
  icon?: ReactNode
  children?: ReactNode
  /** Action buttons, right-aligned. */
  footer?: ReactNode
  /**
   * `alertdialog` for confirmations of consequential actions: the backdrop does
   * not dismiss it, so the user must choose explicitly (Escape still cancels).
   */
  role?: 'dialog' | 'alertdialog'
  /** Element focused on open (use the safest action for destructive confirms). */
  initialFocusRef?: RefObject<HTMLElement | null>
  className?: string
}

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  icon,
  children,
  footer,
  role = 'dialog',
  initialFocusRef,
  className,
}: DialogProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const descriptionId = useId()

  useModal({
    open,
    onClose: () => {
      onOpenChange(false)
    },
    containerRef: panelRef,
    initialFocusRef,
  })

  if (!open) return null

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center p-4 sm:items-center">
      <div
        role="presentation"
        className="absolute inset-0 animate-fade-in bg-overlay backdrop-blur-[2px]"
        onClick={
          role === 'dialog'
            ? () => {
                onOpenChange(false)
              }
            : undefined
        }
      />
      <div
        ref={panelRef}
        role={role}
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={cn(
          'relative w-full max-w-md animate-dialog-in rounded-xl border border-border-strong bg-surface-raised shadow-overlay outline-none',
          className,
        )}
      >
        <div className="flex gap-4 p-5">
          {icon ? <div className="shrink-0">{icon}</div> : null}
          <div className="min-w-0 flex-1 space-y-1.5">
            <h2 id={titleId} className="text-base font-semibold tracking-tight text-fg">
              {title}
            </h2>
            {description ? (
              <p id={descriptionId} className="text-sm leading-relaxed text-fg-muted">
                {description}
              </p>
            ) : null}
            {children ? <div className="pt-2">{children}</div> : null}
          </div>
        </div>
        {footer ? (
          <div className="flex flex-col-reverse gap-2 border-t border-border px-5 py-3.5 sm:flex-row sm:justify-end">
            {footer}
          </div>
        ) : null}
      </div>
    </div>,
    document.body,
  )
}
