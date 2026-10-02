import { Layers } from 'lucide-react'

import { PlaceholderPage } from '@/components/layout/PlaceholderPage'

export function StrategiesPage() {
  return (
    <PlaceholderPage
      title="Strategies"
      description="Trend-following, mean-reversion and breakout strategies, gated by market regime."
      icon={Layers}
      emptyTitle="Strategy health will appear here"
      emptyDescription="Each strategy gets a card with its current signals, the regimes it is allowed to trade, and its capital allocation."
      planned={[
        'Live signals and regime gates',
        'Allocation weights per regime',
        'Per-strategy performance from the journal',
        'Enable / pause controls',
      ]}
    />
  )
}
