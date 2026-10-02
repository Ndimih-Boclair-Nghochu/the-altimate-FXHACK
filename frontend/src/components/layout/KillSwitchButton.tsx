import { OctagonX } from 'lucide-react'
import { useRef, useState } from 'react'

import { Button, Dialog } from '@/components/ui'

interface KillSwitchButtonProps {
  /** Engage the kill switch. Not wired to the backend yet (Stage 5/6). */
  onConfirm?: () => void
}

/**
 * Emergency stop. Guarded by a confirmation dialog whose default focus is
 * "Cancel", so a stray Enter can never trigger it.
 */
export function KillSwitchButton({ onConfirm }: KillSwitchButtonProps) {
  const [open, setOpen] = useState(false)
  const cancelRef = useRef<HTMLButtonElement>(null)

  return (
    <>
      <Button
        variant="danger-subtle"
        size="sm"
        aria-haspopup="dialog"
        onClick={() => {
          setOpen(true)
        }}
        className="max-sm:size-8 max-sm:px-0"
      >
        <OctagonX aria-hidden="true" />
        <span className="max-sm:sr-only">Kill switch</span>
      </Button>

      <Dialog
        open={open}
        onOpenChange={setOpen}
        role="alertdialog"
        initialFocusRef={cancelRef}
        icon={
          <div className="flex size-10 items-center justify-center rounded-full border border-loss/30 bg-loss/12 text-loss">
            <OctagonX className="size-5" aria-hidden="true" />
          </div>
        }
        title="Engage the kill switch?"
        description="This immediately closes every open position at market and blocks all new orders until trading is manually re-enabled."
        footer={
          <>
            <Button
              ref={cancelRef}
              variant="secondary"
              onClick={() => {
                setOpen(false)
              }}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                onConfirm?.()
                setOpen(false)
              }}
            >
              Flatten &amp; halt trading
            </Button>
          </>
        }
      >
        {onConfirm ? null : (
          <p className="rounded-lg border border-border bg-surface-muted px-3 py-2 text-xs leading-relaxed text-fg-muted">
            Preview only: the trading engine isn’t connected yet, so confirming has no effect.
          </p>
        )}
      </Dialog>
    </>
  )
}
