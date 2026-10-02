import { QueryClient } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { vi } from 'vitest'

import { Providers } from '@/app/Providers'
import { routes } from '@/app/routes'
import { type HealthResponse } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

export function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  })
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** Answer `GET /api/health` with the given payload (or fail the request). */
export function mockHealth(health: HealthResponse | 'offline') {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    if (health === 'offline') return Promise.reject(new TypeError('Failed to fetch'))
    if (url.startsWith('/api/health')) return Promise.resolve(jsonResponse(health))
    return Promise.resolve(jsonResponse({ detail: 'Not found' }, 404))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

export { jsonResponse }

/** Render the full app (shell + routes) at `path` with fresh state. */
export function renderApp(path = '/') {
  useUiStore.setState({ mobileNavOpen: false, sidebarCollapsed: false })
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const queryClient = createTestQueryClient()
  const user = userEvent.setup()
  const utils = render(
    <Providers queryClient={queryClient}>
      <RouterProvider router={router} />
    </Providers>,
  )
  return { ...utils, user, router, queryClient }
}
