import { type RefObject, useEffect, useEffectEvent } from 'react'

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function focusableWithin(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE))
}

interface UseModalOptions {
  open: boolean
  onClose: () => void
  containerRef: RefObject<HTMLElement | null>
  /** Element to focus on open; defaults to the first focusable element. */
  initialFocusRef?: RefObject<HTMLElement | null>
}

/**
 * Shared modal behaviour for dialogs and drawers: moves focus in on open,
 * traps Tab inside, closes on Escape, locks page scroll, and restores focus to
 * the previously focused element on close.
 */
export function useModal({ open, onClose, containerRef, initialFocusRef }: UseModalOptions) {
  const close = useEffectEvent(onClose)

  useEffect(() => {
    if (!open) return
    const container = containerRef.current
    if (!container) return

    const previouslyFocused =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    const initial = initialFocusRef?.current ?? focusableWithin(container)[0] ?? container
    initial.focus()

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        close()
        return
      }
      if (event.key !== 'Tab') return
      const items = focusableWithin(container)
      const first = items[0]
      const last = items[items.length - 1]
      if (!first || !last) {
        event.preventDefault()
        container.focus()
        return
      }
      const active = document.activeElement
      if (event.shiftKey && (active === first || !container.contains(active))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && (active === last || !container.contains(active))) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
      previouslyFocused?.focus()
    }
  }, [open, containerRef, initialFocusRef])
}
