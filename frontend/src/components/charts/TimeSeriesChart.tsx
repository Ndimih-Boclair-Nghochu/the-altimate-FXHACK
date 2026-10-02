import {
  AreaSeries,
  ColorType,
  createChart,
  CrosshairMode,
  type DeepPartial,
  type AreaSeriesPartialOptions,
  type ChartOptions,
  type IChartApi,
  type ISeriesApi,
  LineStyle,
  type UTCTimestamp,
} from 'lightweight-charts'
import { useEffect, useRef } from 'react'

import { cn } from '@/lib/cn'
import { useThemeStore } from '@/stores/theme'

import { type ChartTokens, readChartTokens, withAlpha } from './chartTheme'

export interface TimeSeriesPoint {
  /** Unix time in seconds (UTC). */
  time: UTCTimestamp
  value: number
}

type Tone = 'accent' | 'profit' | 'loss'

function chartOptions(tokens: ChartTokens): DeepPartial<ChartOptions> {
  return {
    layout: {
      background: { type: ColorType.Solid, color: 'transparent' },
      textColor: tokens.textMuted,
      fontFamily: tokens.fontFamily,
      fontSize: 11,
      // Attribution is rendered as a link in the figure caption instead: the built-in
      // logo injects an inline <style>, which the Content-Security-Policy blocks.
      attributionLogo: false,
    },
    grid: {
      vertLines: { visible: false },
      horzLines: { color: withAlpha(tokens.border, 0.7), style: LineStyle.Solid },
    },
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false, timeVisible: true },
    crosshair: {
      mode: CrosshairMode.Magnet,
      vertLine: { color: tokens.textMuted, labelBackgroundColor: tokens.surface },
      horzLine: { color: tokens.textMuted, labelBackgroundColor: tokens.surface },
    },
  }
}

function seriesOptions(tokens: ChartTokens, tone: Tone): AreaSeriesPartialOptions {
  const color = tokens[tone]
  return {
    lineColor: color,
    lineWidth: 2,
    topColor: withAlpha(color, 0.22),
    bottomColor: withAlpha(color, 0),
    priceLineVisible: false,
    lastValueVisible: true,
    crosshairMarkerRadius: 4,
  }
}

interface TimeSeriesChartProps {
  data: readonly TimeSeriesPoint[]
  /** Accessible description of what the chart shows. */
  label: string
  tone?: Tone
  className?: string
}

/**
 * Themed area chart (lightweight-charts) that follows the app's light/dark
 * tokens, resizes with its container and cleans up on unmount.
 */
export function TimeSeriesChart({ data, label, tone = 'accent', className }: TimeSeriesChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Area'> | null>(null)
  const theme = useThemeStore((s) => s.resolved)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const chart = createChart(container, { autoSize: true })
    chartRef.current = chart
    seriesRef.current = chart.addSeries(AreaSeries)
    return () => {
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [])

  useEffect(() => {
    const tokens = readChartTokens()
    chartRef.current?.applyOptions(chartOptions(tokens))
    seriesRef.current?.applyOptions(seriesOptions(tokens, tone))
  }, [theme, tone])

  useEffect(() => {
    seriesRef.current?.setData([...data])
    chartRef.current?.timeScale().fitContent()
  }, [data])

  return (
    <figure className={cn('relative flex h-full min-h-48 flex-col', className)}>
      <div ref={containerRef} role="img" aria-label={label} className="min-h-0 flex-1" />
      <figcaption className="pt-1 text-right text-2xs text-fg-subtle">
        Charts by{' '}
        <a
          href="https://www.tradingview.com/"
          target="_blank"
          rel="noopener noreferrer"
          className="underline-offset-2 hover:text-fg-muted hover:underline"
        >
          TradingView
        </a>
      </figcaption>
    </figure>
  )
}
