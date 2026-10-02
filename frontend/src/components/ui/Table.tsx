import { type ComponentProps } from 'react'

import { cn } from '@/lib/cn'

type Align = 'left' | 'right' | 'center'

const alignClass: Record<Align, string> = {
  left: 'text-left',
  right: 'text-right',
  center: 'text-center',
}

interface TableProps extends ComponentProps<'table'> {
  /** Classes for the scroll container (e.g. a max height to enable the sticky header). */
  containerClassName?: string
  /** Accessible name for the scroll region when it can scroll. */
  label?: string
}

/**
 * Data table. The wrapper scrolls in both directions so wide tables never
 * cause page-level horizontal scroll; the header stays pinned while scrolling.
 */
export function Table({ className, containerClassName, label, ...props }: TableProps) {
  return (
    <div
      className={cn('relative w-full overflow-auto', containerClassName)}
      role={label ? 'region' : undefined}
      aria-label={label}
      tabIndex={label ? 0 : undefined}
    >
      <table
        className={cn('w-full caption-bottom border-separate border-spacing-0 text-sm', className)}
        {...props}
      />
    </div>
  )
}

export function TableHeader({ className, ...props }: ComponentProps<'thead'>) {
  return <thead className={cn('sticky top-0 z-10 bg-surface', className)} {...props} />
}

export function TableBody({ className, ...props }: ComponentProps<'tbody'>) {
  return <tbody className={cn('[&>tr:last-child>td]:border-b-0', className)} {...props} />
}

export function TableRow({ className, ...props }: ComponentProps<'tr'>) {
  return (
    <tr
      className={cn(
        'transition-colors duration-100 [tbody>&]:hover:bg-surface-muted/60',
        className,
      )}
      {...props}
    />
  )
}

interface CellProps {
  align?: Align
  /** Numeric column: right-aligned, monospaced tabular figures. */
  numeric?: boolean
}

export function TableHead({
  className,
  align = 'left',
  numeric = false,
  scope = 'col',
  ...props
}: ComponentProps<'th'> & CellProps) {
  return (
    <th
      scope={scope}
      className={cn(
        'h-9 border-b border-border px-3 text-2xs font-medium tracking-wider whitespace-nowrap text-fg-muted uppercase first:pl-5 last:pr-5',
        alignClass[numeric ? 'right' : align],
        className,
      )}
      {...props}
    />
  )
}

export function TableCell({
  className,
  align = 'left',
  numeric = false,
  ...props
}: ComponentProps<'td'> & CellProps) {
  return (
    <td
      className={cn(
        'h-11 border-b border-border px-3 whitespace-nowrap text-fg tabular-nums first:pl-5 last:pr-5',
        numeric && 'numeric text-[0.8125rem]',
        alignClass[numeric ? 'right' : align],
        className,
      )}
      {...props}
    />
  )
}

export function TableCaption({ className, ...props }: ComponentProps<'caption'>) {
  return <caption className={cn('mt-3 text-xs text-fg-muted', className)} {...props} />
}
