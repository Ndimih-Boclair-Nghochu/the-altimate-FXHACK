/**
 * Bridges the CSS design tokens to canvas-based charts, which can't read CSS
 * variables themselves. Tokens are plain hex so every chart library parses them.
 */

export interface ChartTokens {
  surface: string
  text: string
  textMuted: string
  border: string
  accent: string
  profit: string
  loss: string
  fontFamily: string
}

const FALLBACK: ChartTokens = {
  surface: '#111318',
  text: '#ecedf0',
  textMuted: '#9097a3',
  border: '#22252d',
  accent: '#5b95ff',
  profit: '#3ddc97',
  loss: '#ef5350',
  fontFamily: 'ui-sans-serif, system-ui, sans-serif',
}

export function readChartTokens(element: Element = document.documentElement): ChartTokens {
  const style = getComputedStyle(element)
  const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback
  return {
    surface: read('--surface', FALLBACK.surface),
    text: read('--text', FALLBACK.text),
    textMuted: read('--text-muted', FALLBACK.textMuted),
    border: read('--border', FALLBACK.border),
    accent: read('--accent', FALLBACK.accent),
    profit: read('--profit', FALLBACK.profit),
    loss: read('--loss', FALLBACK.loss),
    fontFamily: read('--font-sans', FALLBACK.fontFamily),
  }
}

/** `#rrggbb` + alpha → `rgba(r, g, b, a)`; other formats are returned unchanged. */
export function withAlpha(color: string, alpha: number): string {
  const match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(color)
  if (!match) return color
  const [r, g, b] = match.slice(1, 4).map((part) => parseInt(part, 16))
  return `rgba(${r ?? 0}, ${g ?? 0}, ${b ?? 0}, ${alpha})`
}
