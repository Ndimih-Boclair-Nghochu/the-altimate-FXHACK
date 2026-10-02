import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach, vi } from 'vitest'

// jsdom has no matchMedia; default to a dark OS preference.
function installMatchMedia(prefersDark = true) {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: vi.fn((query: string) => ({
      matches: query.includes('dark') ? prefersDark : !prefersDark,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
}

installMatchMedia()

beforeEach(() => {
  // Tests must never touch the network: any un-mocked request fails loudly.
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.reject(new TypeError('Network access is disabled in tests'))),
  )
})

afterEach(() => {
  cleanup()
  window.localStorage.clear()
  document.body.style.overflow = ''
})
