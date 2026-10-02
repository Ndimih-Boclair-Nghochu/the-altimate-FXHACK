import { Compass } from 'lucide-react'
import { Link, useLocation } from 'react-router'

import { buttonClasses, Card, EmptyState } from '@/components/ui'

export function NotFoundPage() {
  const { pathname } = useLocation()
  return (
    <>
      <title>Page not found · Altimate FX</title>
      <h1 className="sr-only">Page not found</h1>
      <Card className="mt-8">
        <EmptyState
          icon={Compass}
          title="404 — page not found"
          description={
            <>
              Nothing lives at <code className="numeric text-fg">{pathname}</code>. Check the
              address, or head back to the overview.
            </>
          }
        >
          <Link to="/" className={buttonClasses({ variant: 'primary' })}>
            Back to overview
          </Link>
        </EmptyState>
      </Card>
    </>
  )
}
