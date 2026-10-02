import { render, screen } from '@testing-library/react'
import { type UTCTimestamp } from 'lightweight-charts'
import { act } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useThemeStore } from '@/stores/theme'

import { withAlpha } from './chartTheme'
import { TimeSeriesChart } from './TimeSeriesChart'

// Canvas charts can't render in jsdom; verify the lifecycle against a fake.
const fake = vi.hoisted(() => {
  const series = { setData: vi.fn(), applyOptions: vi.fn() }
  const chart = {
    addSeries: vi.fn(() => series),
    applyOptions: vi.fn(),
    timeScale: vi.fn(() => ({ fitContent: vi.fn() })),
    remove: vi.fn(),
  }
  return { series, chart, createChart: vi.fn(() => chart) }
})

vi.mock('lightweight-charts', () => ({
  AreaSeries: { type: 'Area' },
  ColorType: { Solid: 'solid' },
  CrosshairMode: { Magnet: 1 },
  LineStyle: { Solid: 0 },
  createChart: fake.createChart,
}))

const data = [
  { time: 1_700_000_000 as UTCTimestamp, value: 100 },
  { time: 1_700_086_400 as UTCTimestamp, value: 101.5 },
]

describe('TimeSeriesChart', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useThemeStore.getState().setPreference('dark')
  })

  it('creates a chart, loads data, disables the CSP-incompatible logo and cleans up', () => {
    const { unmount } = render(<TimeSeriesChart data={data} label="Equity curve" />)

    expect(screen.getByRole('img', { name: 'Equity curve' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'TradingView' })).toHaveAttribute(
      'rel',
      'noopener noreferrer',
    )
    expect(fake.createChart).toHaveBeenCalledOnce()
    expect(fake.series.setData).toHaveBeenCalledWith(data)
    expect(fake.chart.applyOptions).toHaveBeenCalledWith(
      expect.objectContaining({
        layout: expect.objectContaining({ attributionLogo: false }) as unknown,
      }),
    )

    unmount()
    expect(fake.chart.remove).toHaveBeenCalledOnce()
  })

  it('re-applies colours when the theme changes', () => {
    render(<TimeSeriesChart data={data} label="Equity curve" />)
    const calls = fake.chart.applyOptions.mock.calls.length

    act(() => {
      useThemeStore.getState().setPreference('light')
    })

    expect(fake.chart.applyOptions.mock.calls.length).toBeGreaterThan(calls)
    expect(fake.createChart).toHaveBeenCalledOnce()
  })
})

describe('withAlpha', () => {
  it('converts hex tokens to rgba and leaves other formats alone', () => {
    expect(withAlpha('#ff0000', 0.5)).toBe('rgba(255, 0, 0, 0.5)')
    expect(withAlpha('rgb(1 2 3)', 0.5)).toBe('rgb(1 2 3)')
  })
})
