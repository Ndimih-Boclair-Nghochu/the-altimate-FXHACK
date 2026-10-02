import { X } from 'lucide-react'
import { type ReactNode, useRef } from 'react'
import { createPortal } from 'react-dom'

import { useModal } from '@/hooks/useModal'
import { cn } from '@/lib/cn'

import { Button } from './Button'

interface DrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Accessible name for the drawer. */
  label: string
  /** Content for the drawer's header row (e.g. the brand). */
  header?: ReactNode
  children: ReactNode
  className?: string
}

/** Left-edge sheet used for navigation on small screens. */
export function Drawer({ open, onOpenChange, label, header, children, className }: DrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const close = () => {
    onOpenChange(false)
  }

  useModal({ open, onClose: close, containerRef: panelRef })

  if (!open) return null

  return createPortal(
    <div className="fixed inset-0 z-50">
      <div
        role="presentation"
        className="absolute inset-0 animate-fade-in bg-overlay backdrop-blur-[2px]"
        onClick={close}
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        tabIndex={-1}
        className={cn(
          'absolute inset-y-0 left-0 flex w-[min(18rem,85vw)] animate-drawer-in flex-col border-r border-border bg-surface shadow-overlay outline-none',
          className,
        )}
      >
        <div className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-border px-4">
          {header}
          <Button variant="ghost" size="icon-sm" aria-label="Close navigation" onClick={close}>
            <X aria-hidden="true" />
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>,
    document.body,
  )
}
