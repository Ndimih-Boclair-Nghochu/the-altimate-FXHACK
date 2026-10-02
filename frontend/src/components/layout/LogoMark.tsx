import { useId } from 'react'

import { cn } from '@/lib/cn'

/** Brand mark: a rising, peaked line — altitude meets price action. */
export function LogoMark({ className }: { className?: string }) {
  const gradientId = useId()
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={cn('size-6 shrink-0', className)}>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#5b95ff" />
          <stop offset="1" stopColor="#2554d8" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill={`url(#${gradientId})`} />
      <path
        d="M7 22.5 12.75 13 16.75 18.5 20.5 10.5 25 22.5"
        fill="none"
        stroke="#fff"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function Brand({ className }: { className?: string }) {
  return (
    <span className={cn('flex items-center gap-2.5', className)}>
      <LogoMark />
      <span className="text-[0.9375rem] font-semibold tracking-tight text-fg">Altimate FX</span>
    </span>
  )
}
