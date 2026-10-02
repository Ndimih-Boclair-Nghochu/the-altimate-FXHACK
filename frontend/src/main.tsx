import '@fontsource-variable/inter'
import '@fontsource-variable/jetbrains-mono'
import './index.css'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'

import { Providers } from '@/app/Providers'
import { routes } from '@/app/routes'
import { createQueryClient } from '@/lib/queryClient'
import { initTheme } from '@/stores/theme'

initTheme()

const router = createBrowserRouter(routes)
const queryClient = createQueryClient()

const container = document.getElementById('root')
if (!container) throw new Error('Root element #root not found')

createRoot(container).render(
  <StrictMode>
    <Providers queryClient={queryClient}>
      <RouterProvider router={router} />
    </Providers>
  </StrictMode>,
)
