import {
  cloneElement,
  type CSSProperties,
  type FocusEvent,
  type MouseEvent,
  type PointerEvent,
  type ReactElement,
  type ReactNode,
  useEffect,
  useId,
  useState,
} from 'react'
import { createPortal } from 'react-dom'

type Side = 'top' | 'bottom' | 'left' | 'right'
type Align = 'start' | 'center' | 'end'

const GAP = 6

function computePosition(rect: DOMRect, side: Side, align: Align): CSSProperties {
  const vertical = side === 'top' || side === 'bottom'
  if (vertical) {
    const top = side === 'bottom' ? rect.bottom + GAP : rect.top - GAP
    const left =
      align === 'start' ? rect.left : align === 'end' ? rect.right : rect.left + rect.width / 2
    const x = align === 'start' ? '0' : align === 'end' ? '-100%' : '-50%'
    const y = side === 'top' ? '-100%' : '0'
    return { top, left, transform: `translate(${x}, ${y})` }
  }
  const left = side === 'right' ? rect.right + GAP + 2 : rect.left - GAP - 2
  const top = rect.top + rect.height / 2
  return { top, left, transform: `translate(${side === 'left' ? '-100%' : '0'}, -50%)` }
}

interface TriggerProps {
  'aria-describedby'?: string
  onMouseEnter?: (event: MouseEvent<HTMLElement>) => void
  onMouseLeave?: (event: MouseEvent<HTMLElement>) => void
  onFocus?: (event: FocusEvent<HTMLElement>) => void
  onBlur?: (event: FocusEvent<HTMLElement>) => void
  onPointerDown?: (event: PointerEvent<HTMLElement>) => void
}

interface TooltipProps {
  content: ReactNode
  /** A single focusable element (button, link) that accepts mouse/focus handlers. */
  children: ReactElement<TriggerProps>
  side?: Side
  align?: Align
  /** Hover delay in ms (keyboard focus shows immediately). */
  delay?: number
  disabled?: boolean
  /**
   * Link the tooltip to the trigger via aria-describedby (default). Turn off when
   * the tooltip only repeats the trigger's accessible name.
   */
  describe?: boolean
}

/** Only keyboard focus should open a tooltip; a mouse click shouldn't leave one behind. */
function isFocusVisible(element: Element): boolean {
  try {
    return element.matches(':focus-visible')
  } catch {
    return true
  }
}

/**
 * Lightweight tooltip shown on hover and keyboard focus, dismissed with Escape.
 * Rendered in a portal with fixed positioning so it is never clipped by
 * scrolling or overflow-hidden ancestors. Supplementary only — never put
 * essential information or interactive content in a tooltip.
 */
export function Tooltip({
  content,
  children,
  side = 'bottom',
  align = 'center',
  delay = 250,
  disabled = false,
  describe = true,
}: TooltipProps) {
  const id = useId()
  const [state, setState] = useState<CSSProperties | null>(null)
  const open = state !== null && !disabled

  // Hover intent is handled with an animation delay rather than a timer: the
  // tooltip mounts at once but stays invisible until `delay` has passed.
  const show = (target: HTMLElement, immediate: boolean) => {
    const style = computePosition(target.getBoundingClientRect(), side, align)
    setState(immediate ? style : { ...style, animationDelay: `${delay}ms` })
  }

  const hide = () => {
    setState(null)
  }

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setState(null)
    }
    const onScroll = () => {
      setState(null)
    }
    document.addEventListener('keydown', onKeyDown)
    window.addEventListener('scroll', onScroll, true)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('scroll', onScroll, true)
    }
  }, [open])

  const own = children.props
  const trigger = cloneElement(children, {
    'aria-describedby': describe && open ? id : own['aria-describedby'],
    onMouseEnter: (event) => {
      own.onMouseEnter?.(event)
      show(event.currentTarget, false)
    },
    onMouseLeave: (event) => {
      own.onMouseLeave?.(event)
      hide()
    },
    onFocus: (event) => {
      own.onFocus?.(event)
      if (isFocusVisible(event.currentTarget)) show(event.currentTarget, true)
    },
    onBlur: (event) => {
      own.onBlur?.(event)
      hide()
    },
    onPointerDown: (event) => {
      own.onPointerDown?.(event)
      hide()
    },
  })

  return (
    <>
      {trigger}
      {open
        ? createPortal(
            <div
              role="tooltip"
              id={id}
              style={state}
              aria-hidden={describe ? undefined : true}
              className="pointer-events-none fixed z-[60] max-w-xs animate-tooltip-in rounded-md border border-border-strong bg-surface-raised px-2 py-1 text-xs text-fg shadow-overlay [animation-fill-mode:both]"
            >
              {content}
            </div>,
            document.body,
          )
        : null}
    </>
  )
}
