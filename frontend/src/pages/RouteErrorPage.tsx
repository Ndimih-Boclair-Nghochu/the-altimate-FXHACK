import { TriangleAlert } from 'lucide-react'
import { isRouteErrorResponse, Link, useRouteError } from 'react-router'

import { buttonClasses, Card, EmptyState } from '@/components/ui'

function describe(error: unknown): string {
  if (isRouteErrorResponse(error)) return `${error.status} ${error.statusText}`
  if (error instanceof Error) return error.message
  return 'An unexpected error occurred.'
}

/** Rendered inside the app shell when a page throws, so navigation keeps working. */
export function RouteErrorPage() {
  const error = useRouteError()
  return (
    <>
      <title>Something went wrong · Altimate FX</title>
      <h1 className="sr-only">Something went wrong</h1>
      <Card className="mt-8">
        <EmptyState
          icon={TriangleAlert}
          title="This view hit an error"
          description={
            <>
              <span className="block">{describe(error)}</span>
              <span className="mt-1 block">
                Trading is unaffected — the engine runs on the server, not in this page.
              </span>
            </>
          }
        >
          <button
            type="button"
            className={buttonClasses({ variant: 'secondary' })}
            onClick={() => {
              window.location.reload()
            }}
          >
            Reload
          </button>
          <Link to="/" className={buttonClasses({ variant: 'primary' })}>
            Back to overview
          </Link>
        </EmptyState>
      </Card>
    </>
  )
}
