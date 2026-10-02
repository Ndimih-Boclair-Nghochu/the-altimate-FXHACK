import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { formatPercent, MINUS } from '@/lib/format'

import { Stat } from './Stat'

const pct = (v: number) => formatPercent(v, { signed: true })

describe('Stat', () => {
  it('shows a gain with a plus sign, an up label and profit colour', () => {
    const { container } = render(
      <Stat
        label="Today’s P&L"
        value="$1,204.00"
        delta={1.8}
        formatDelta={pct}
        deltaLabel="today"
      />,
    )
    const delta = container.querySelector('[data-direction]')
    expect(screen.getByRole('term')).toHaveTextContent('Today’s P&L')
    expect(screen.getByText('$1,204.00')).toBeInTheDocument()
    expect(delta).toHaveAttribute('data-direction', 'up')
    expect(delta).toHaveTextContent('Up+1.80%today')
    expect(delta).toHaveClass('text-profit')
    expect(delta?.querySelector('svg')).not.toBeNull()
  })

  it('shows a loss with a minus sign, a down label and loss colour', () => {
    const { container } = render(<Stat label="P&L" value="x" delta={-0.4} formatDelta={pct} />)
    const delta = container.querySelector('[data-direction]')
    expect(delta).toHaveTextContent(`Down${MINUS}0.40%`)
    expect(delta).toHaveClass('text-loss')
  })

  it('inverts colours (not signs) when a rise is bad', () => {
    const { container } = render(
      <Stat label="Drawdown" value="x" delta={2} formatDelta={pct} invertDeltaColor />,
    )
    const delta = container.querySelector('[data-direction]')
    expect(delta).toHaveTextContent('+2.00%')
    expect(delta).toHaveClass('text-loss')
  })

  it('renders a neutral unchanged state', () => {
    const { container } = render(<Stat label="P&L" value="x" delta={0} formatDelta={pct} />)
    expect(container.querySelector('[data-direction]')).toHaveClass('text-fg-muted')
  })

  it('renders an em dash for missing values and a skeleton while loading', () => {
    const { rerender, container } = render(<Stat label="Equity" value={null} />)
    expect(screen.getByText('—')).toBeInTheDocument()

    rerender(<Stat label="Equity" value={null} loading hint="Balance + unrealised P&L" />)
    expect(screen.getByText('Loading')).toBeInTheDocument()
    expect(container.querySelector('.skeleton')).not.toBeNull()
    expect(screen.getByText('Balance + unrealised P&L')).toBeInTheDocument()
  })
})
