import { type ComponentProps } from 'react'

import { cn } from '@/lib/cn'

/** Placeholder block for content that is loading. Purely decorative. */
export function Skeleton({ className, ...props }: ComponentProps<'div'>) {
  return <div aria-hidden="true" className={cn('skeleton rounded-md', className)} {...props} />
}
