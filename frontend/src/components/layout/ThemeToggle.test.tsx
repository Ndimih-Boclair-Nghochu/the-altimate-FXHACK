import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { THEME_STORAGE_KEY, useThemeStore } from '@/stores/theme'

import { ThemeToggle } from './ThemeToggle'

const html = document.documentElement

describe('ThemeToggle', () => {
  beforeEach(() => {
    useThemeStore.getState().setPreference('dark')
    window.localStorage.clear()
  })

  it('switches the dark class on <html> back and forth', async () => {
    const user = userEvent.setup()
    render(<ThemeToggle />)
    expect(html).toHaveClass('dark')

    await user.click(screen.getByRole('button', { name: 'Switch to light theme' }))
    expect(html).not.toHaveClass('dark')
    expect(html.style.colorScheme).toBe('light')

    await user.click(screen.getByRole('button', { name: 'Switch to dark theme' }))
    expect(html).toHaveClass('dark')
    expect(html.style.colorScheme).toBe('dark')
  })

  it('persists the choice in localStorage', async () => {
    const user = userEvent.setup()
    render(<ThemeToggle />)

    await user.click(screen.getByRole('button', { name: 'Switch to light theme' }))
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('light')
  })

  it('still works when localStorage is unavailable', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('Blocked', 'SecurityError')
    })
    const user = userEvent.setup()
    render(<ThemeToggle />)

    await user.click(screen.getByRole('button', { name: 'Switch to light theme' }))
    expect(html).not.toHaveClass('dark')
  })

  it('follows the system preference when set to "system"', () => {
    useThemeStore.getState().setPreference('system')
    // The test environment reports a dark OS preference.
    expect(useThemeStore.getState().resolved).toBe('dark')
    expect(html).toHaveClass('dark')
  })
})
