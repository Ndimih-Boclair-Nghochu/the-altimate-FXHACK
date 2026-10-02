import {
  type ComponentProps,
  createContext,
  type KeyboardEvent,
  type ReactNode,
  use,
  useId,
  useState,
} from 'react'

import { cn } from '@/lib/cn'

type TabsVariant = 'underline' | 'segmented'

interface TabsContextValue {
  baseId: string
  value: string
  select: (value: string) => void
  variant: TabsVariant
}

const TabsContext = createContext<TabsContextValue | null>(null)

function useTabs(component: string): TabsContextValue {
  const ctx = use(TabsContext)
  if (!ctx) throw new Error(`<${component}> must be used inside <Tabs>`)
  return ctx
}

const safeId = (value: string) => value.replace(/[^\w-]/g, '_')

interface TabsProps {
  /** Controlled value. */
  value?: string
  /** Initial value when uncontrolled. */
  defaultValue?: string
  onValueChange?: (value: string) => void
  /** `underline` for page sections, `segmented` for compact range pickers. */
  variant?: TabsVariant
  className?: string
  children: ReactNode
}

/** WAI-ARIA tabs with automatic activation and arrow/Home/End keyboard support. */
export function Tabs({
  value,
  defaultValue = '',
  onValueChange,
  variant = 'underline',
  className,
  children,
}: TabsProps) {
  const baseId = useId()
  const [internal, setInternal] = useState(defaultValue)
  const current = value ?? internal

  const select = (next: string) => {
    if (value === undefined) setInternal(next)
    onValueChange?.(next)
  }

  return (
    <TabsContext value={{ baseId, value: current, select, variant }}>
      <div className={className}>{children}</div>
    </TabsContext>
  )
}

interface TabsListProps extends ComponentProps<'div'> {
  /** Accessible name for the tab list. */
  label: string
}

export function TabsList({ label, className, children, ...props }: TabsListProps) {
  const { variant } = useTabs('TabsList')

  return (
    <div
      role="tablist"
      aria-label={label}
      aria-orientation="horizontal"
      className={cn(
        variant === 'segmented'
          ? 'inline-flex items-center gap-0.5 rounded-lg border border-border bg-surface-muted p-0.5'
          : 'flex items-center gap-4 border-b border-border',
        className,
      )}
      {...props}
    >
      {children}
    </div>
  )
}

/** Arrow/Home/End move focus between tabs and activate them (automatic activation). */
function onTabKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
  const list = event.currentTarget.closest('[role="tablist"]')
  if (!list) return
  const tabs = Array.from(list.querySelectorAll<HTMLButtonElement>('[role="tab"]:not(:disabled)'))
  const index = tabs.indexOf(event.currentTarget)
  let next: number
  switch (event.key) {
    case 'ArrowRight':
      next = (index + 1) % tabs.length
      break
    case 'ArrowLeft':
      next = (index - 1 + tabs.length) % tabs.length
      break
    case 'Home':
      next = 0
      break
    case 'End':
      next = tabs.length - 1
      break
    default:
      return
  }
  event.preventDefault()
  const target = tabs[next]
  target?.focus()
  target?.click()
}

interface TabsTriggerProps extends Omit<ComponentProps<'button'>, 'value'> {
  value: string
}

export function TabsTrigger({ value, className, children, ...props }: TabsTriggerProps) {
  const { baseId, value: current, select, variant } = useTabs('TabsTrigger')
  const selected = current === value
  const id = safeId(value)

  return (
    <button
      type="button"
      role="tab"
      id={`${baseId}-tab-${id}`}
      aria-selected={selected}
      aria-controls={`${baseId}-panel-${id}`}
      tabIndex={selected ? 0 : -1}
      data-state={selected ? 'active' : 'inactive'}
      onKeyDown={onTabKeyDown}
      onClick={() => {
        select(value)
      }}
      className={cn(
        'inline-flex items-center justify-center gap-1.5 text-[0.8125rem] font-medium whitespace-nowrap transition-colors duration-150 disabled:pointer-events-none disabled:opacity-50',
        variant === 'segmented'
          ? cn(
              'h-7 rounded-md px-2.5',
              selected
                ? 'bg-surface-raised text-fg shadow-sm ring-1 ring-border'
                : 'text-fg-muted hover:text-fg',
            )
          : cn(
              '-mb-px h-9 border-b-2 px-0.5',
              selected ? 'border-accent text-fg' : 'border-transparent text-fg-muted hover:text-fg',
            ),
        className,
      )}
      {...props}
    >
      {children}
    </button>
  )
}

interface TabsContentProps extends ComponentProps<'div'> {
  value: string
}

export function TabsContent({ value, className, children, ...props }: TabsContentProps) {
  const { baseId, value: current } = useTabs('TabsContent')
  const id = safeId(value)
  if (current !== value) return null
  return (
    <div
      role="tabpanel"
      id={`${baseId}-panel-${id}`}
      aria-labelledby={`${baseId}-tab-${id}`}
      tabIndex={0}
      className={className}
      {...props}
    >
      {children}
    </div>
  )
}
