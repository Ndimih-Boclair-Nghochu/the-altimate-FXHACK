import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { mockHealth, renderApp } from '@/test/utils'

import { ALL_NAV } from './nav'

describe('App shell', () => {
  it('renders the brand, primary navigation, top-bar controls and main content', () => {
    mockHealth({ status: 'ok', version: '0.1.0', mode: 'paper' })
    renderApp('/')

    const banner = screen.getByRole('banner')
    expect(within(banner).getByText('Altimate FX')).toBeInTheDocument()
    expect(within(banner).getByRole('button', { name: /kill switch/i })).toBeInTheDocument()
    expect(
      within(banner).getByRole('button', { name: /switch to (light|dark) theme/i }),
    ).toBeInTheDocument()

    const nav = screen.getByRole('navigation', { name: 'Primary' })
    for (const item of ALL_NAV) {
      expect(within(nav).getByRole('link', { name: item.label })).toBeInTheDocument()
    }

    expect(screen.getByRole('main')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Overview' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Skip to content' })).toHaveAttribute('href', '#main')
  })

  it('shows a connected backend and the trading mode it reports', async () => {
    mockHealth({ status: 'ok', version: '1.2.3', mode: 'practice' })
    renderApp('/')

    const banner = screen.getByRole('banner')
    expect(await within(banner).findByText('Connected')).toBeInTheDocument()
    expect(within(banner).getByText('Practice').closest('[data-mode]')).toHaveAttribute(
      'data-mode',
      'practice',
    )
  })

  it('shows the backend as offline and the mode as unknown when unreachable', async () => {
    mockHealth('offline')
    renderApp('/')

    const banner = screen.getByRole('banner')
    expect(within(banner).getByText('Connecting')).toBeInTheDocument()
    // The health query retries once before reporting failure.
    expect(
      await within(banner).findByText('Offline', undefined, { timeout: 4000 }),
    ).toBeInTheDocument()
    expect(banner.querySelector('[data-mode]')).toHaveAttribute('data-mode', 'unknown')
  })

  it('collapses the sidebar to an icon rail and remembers the choice', async () => {
    mockHealth({ status: 'ok', version: '0.1.0', mode: 'paper' })
    const { user } = renderApp('/')

    const sidebar = screen.getByRole('complementary', { name: 'Sidebar' })
    expect(sidebar).toHaveAttribute('data-collapsed', 'false')

    await user.click(within(sidebar).getByRole('button', { name: 'Collapse sidebar' }))

    expect(sidebar).toHaveAttribute('data-collapsed', 'true')
    expect(window.localStorage.getItem('altimate-fx.sidebar-collapsed')).toBe('true')
    // Labels stay available to assistive tech when collapsed.
    expect(within(sidebar).getByRole('link', { name: 'Trades' })).toBeInTheDocument()
    expect(within(sidebar).getByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument()
  })
})
