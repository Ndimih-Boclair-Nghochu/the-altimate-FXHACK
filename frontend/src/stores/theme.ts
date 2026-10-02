import { create } from 'zustand'

import { readStorage, writeStorage } from '@/lib/storage'

export type ThemePreference = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

/** Keep in sync with public/theme-init.js (runs before React to avoid a flash). */
export const THEME_STORAGE_KEY = 'altimate-fx.theme'

const DARK_QUERY = '(prefers-color-scheme: dark)'

function isThemePreference(value: unknown): value is ThemePreference {
  return value === 'light' || value === 'dark' || value === 'system'
}

export function getSystemTheme(): ResolvedTheme {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return 'dark'
  return window.matchMedia(DARK_QUERY).matches ? 'dark' : 'light'
}

export function resolveTheme(preference: ThemePreference): ResolvedTheme {
  return preference === 'system' ? getSystemTheme() : preference
}

export function applyTheme(theme: ResolvedTheme): void {
  const root = document.documentElement
  root.classList.toggle('dark', theme === 'dark')
  root.style.colorScheme = theme
}

function readPreference(): ThemePreference {
  const stored = readStorage(THEME_STORAGE_KEY)
  return isThemePreference(stored) ? stored : 'system'
}

interface ThemeState {
  /** What the user chose (defaults to following the OS). */
  preference: ThemePreference
  /** What is actually applied right now. */
  resolved: ResolvedTheme
  setPreference: (preference: ThemePreference) => void
  /** Flip between light and dark (pins an explicit preference). */
  toggle: () => void
  /** Re-resolve after an OS-level change; no-op unless following the system. */
  syncWithSystem: () => void
}

export const useThemeStore = create<ThemeState>()((set, get) => {
  const preference = readPreference()
  return {
    preference,
    resolved: resolveTheme(preference),
    setPreference: (next) => {
      writeStorage(THEME_STORAGE_KEY, next)
      const resolved = resolveTheme(next)
      applyTheme(resolved)
      set({ preference: next, resolved })
    },
    toggle: () => {
      get().setPreference(get().resolved === 'dark' ? 'light' : 'dark')
    },
    syncWithSystem: () => {
      if (get().preference !== 'system') return
      const resolved = getSystemTheme()
      applyTheme(resolved)
      set({ resolved })
    },
  }
})

/**
 * Apply the current theme and follow OS changes while the preference is "system".
 * Returns a cleanup function.
 */
export function initTheme(): () => void {
  applyTheme(useThemeStore.getState().resolved)
  if (typeof window.matchMedia !== 'function') return () => undefined
  const media = window.matchMedia(DARK_QUERY)
  const onChange = () => {
    useThemeStore.getState().syncWithSystem()
  }
  media.addEventListener('change', onChange)
  return () => {
    media.removeEventListener('change', onChange)
  }
}
