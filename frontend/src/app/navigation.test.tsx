import { screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { ALL_NAV } from '@/components/layout/nav'
import { mockHealth, renderApp } from '@/test/utils'

describe('navigation', () => {
  beforeEach(() => {
    mockHealth({ status: 'ok', version: '0.1.0', mode: 'paper' })
  })

  it.each(ALL_NAV.map((item) => [item.label, item.to] as const))(
    'navigates to %s from the sidebar',
    async (label, to) => {
      const { user, router } = renderApp(to === '/' ? '/settings' : '/')
      const nav = screen.getByRole('navigation', { name: 'Primary' })

      await user.click(within(nav).getByRole('link', { name: label }))

      expect(await screen.findByRole('heading', { level: 1, name: label })).toBeInTheDocument()
      expect(router.state.location.pathname).toBe(to)
      expect(within(nav).getByRole('link', { name: label })).toHaveAttribute('aria-current', 'page')
      await waitFor(() => {
        expect(document.title).toBe(`${label} · Altimate FX`)
      })
    },
  )

  it('shows a 404 page inside the shell for unknown routes, with a way back', async () => {
    const { user, router } = renderApp('/definitely/not/here')

    expect(screen.getByRole('heading', { level: 1, name: 'Page not found' })).toBeInTheDocument()
    expect(screen.getByText('/definitely/not/here')).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Primary' })).toBeInTheDocument()

    await user.click(screen.getByRole('link', { name: 'Back to overview' }))
    expect(router.state.location.pathname).toBe('/')
    expect(await screen.findByRole('heading', { level: 1, name: 'Overview' })).toBeInTheDocument()
  })

  it('opens the mobile navigation drawer and closes it after choosing a page', async () => {
    const { user, router } = renderApp('/')

    const menuButton = screen.getByRole('button', { name: 'Open navigation' })
    expect(menuButton).toHaveAttribute('aria-expanded', 'false')
    await user.click(menuButton)

    const drawer = screen.getByRole('dialog', { name: 'Navigation' })
    expect(menuButton).toHaveAttribute('aria-expanded', 'true')
    await user.click(within(drawer).getByRole('link', { name: 'Risk' }))

    expect(screen.queryByRole('dialog', { name: 'Navigation' })).not.toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/risk')
  })

  it('closes the mobile drawer with Escape', async () => {
    const { user } = renderApp('/')

    await user.click(screen.getByRole('button', { name: 'Open navigation' }))
    expect(screen.getByRole('dialog', { name: 'Navigation' })).toBeInTheDocument()

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: 'Navigation' })).not.toBeInTheDocument()
  })
})
