/**
 * Number formatting for figures shown in the dashboard. All output is meant to
 * be rendered with tabular numerals. Negative values use the true minus sign
 * (U+2212) so signed columns line up and read clearly.
 */

export const MINUS = '−'

export type Direction = 'up' | 'down' | 'flat'

export function directionOf(value: number): Direction {
  if (value > 0) return 'up'
  if (value < 0) return 'down'
  return 'flat'
}

interface NumberOptions {
  /** Fixed number of fraction digits (default 2). */
  decimals?: number
  /** Always show a leading + for positive values. */
  signed?: boolean
}

function withMinus(text: string): string {
  return text.replace('-', MINUS)
}

export function formatNumber(value: number, { decimals = 2, signed = false }: NumberOptions = {}) {
  return withMinus(
    new Intl.NumberFormat('en-US', {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
      signDisplay: signed ? 'exceptZero' : 'auto',
    }).format(value),
  )
}

/** Percent from a ratio-free number: `formatPercent(1.25)` → "1.25%". */
export function formatPercent(value: number, options: NumberOptions = {}) {
  return `${formatNumber(value, options)}%`
}

export function formatCurrency(
  value: number,
  currency = 'USD',
  { decimals = 2, signed = false }: NumberOptions = {},
) {
  return withMinus(
    new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency,
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
      signDisplay: signed ? 'exceptZero' : 'auto',
    }).format(value),
  )
}
