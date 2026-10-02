import { ShieldCheck } from 'lucide-react'

import { PlaceholderPage } from '@/components/layout/PlaceholderPage'

export function RiskPage() {
  return (
    <PlaceholderPage
      title="Risk"
      description="Limits and controls enforced on every order before it reaches the broker."
      icon={ShieldCheck}
      emptyTitle="Risk controls will appear here"
      emptyDescription="Live usage of every limit, so you can see how close the system is to a circuit breaker at any moment."
      planned={[
        'Daily and weekly loss limits',
        'Drawdown circuit breaker',
        'Currency exposure by leg',
        'Spread and session filters',
      ]}
    />
  )
}
