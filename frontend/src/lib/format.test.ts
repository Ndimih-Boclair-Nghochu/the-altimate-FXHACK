import { describe, expect, it } from 'vitest'

import { directionOf, formatCurrency, formatNumber, formatPercent, MINUS } from './format'

describe('format', () => {
  it('uses a true minus sign and an explicit plus when signed', () => {
    expect(formatNumber(1234.5)).toBe('1,234.50')
    expect(formatNumber(-3.2)).toBe(`${MINUS}3.20`)
    expect(formatNumber(0.5, { signed: true })).toBe('+0.50')
    expect(formatNumber(0, { signed: true })).toBe('0.00')
    expect(formatPercent(-1.25, { signed: true })).toBe(`${MINUS}1.25%`)
    expect(formatCurrency(-42, 'USD', { signed: true })).toBe(`${MINUS}$42.00`)
    expect(formatNumber(1.23456, { decimals: 5 })).toBe('1.23456')
  })

  it('classifies direction', () => {
    expect(directionOf(2)).toBe('up')
    expect(directionOf(-0.01)).toBe('down')
    expect(directionOf(0)).toBe('flat')
  })
})
