import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { type TradingMode } from '@/lib/api'

import { ModeBadge } from './ModeBadge'

describe('ModeBadge', () => {
  it.each<[TradingMode, string]>([
    ['paper', 'Paper'],
    ['practice', 'Practice'],
    ['live', 'Live'],
  ])('renders the %s mode as "%s"', (mode, label) => {
    const { container } = render(<ModeBadge mode={mode} />)
    const badge = container.querySelector('[data-mode]')

    expect(badge).toHaveAttribute('data-mode', mode)
    expect(screen.getByText(label)).toBeInTheDocument()
    // Screen readers hear what the badge is, not just a bare word.
    expect(badge).toHaveTextContent(`Trading mode: ${label}`)
  })

  it('pulses only for LIVE', () => {
    const { container, rerender } = render(<ModeBadge mode="live" />)
    expect(container.querySelector('.animate-ping')).not.toBeNull()

    for (const mode of ['paper', 'practice'] as const) {
      rerender(<ModeBadge mode={mode} />)
      expect(container.querySelector('.animate-ping')).toBeNull()
    }
  })

  it('uses distinct styling per mode (neutral, accent, solid red)', () => {
    const classesFor = (mode: TradingMode) => {
      const { container, unmount } = render(<ModeBadge mode={mode} />)
      const className = container.querySelector('[data-mode]')?.className ?? ''
      unmount()
      return className
    }
    expect(classesFor('paper')).toContain('text-fg-muted')
    expect(classesFor('practice')).toContain('text-accent')
    expect(classesFor('live')).toContain('bg-loss-solid')
  })

  it('renders an explicit unknown state when the mode is not known', () => {
    const { container } = render(<ModeBadge mode={undefined} />)
    const badge = container.querySelector('[data-mode]')
    expect(badge).toHaveAttribute('data-mode', 'unknown')
    expect(badge).toHaveTextContent(/Trading mode:.*unknown/)
  })
})
