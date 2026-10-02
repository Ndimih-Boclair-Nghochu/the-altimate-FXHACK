import { type QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { type ReactNode } from 'react'

interface ProvidersProps {
  queryClient: QueryClient
  children: ReactNode
}

/** App-wide context providers (shared by main.tsx and the test renderer). */
export function Providers({ queryClient, children }: ProvidersProps) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}
