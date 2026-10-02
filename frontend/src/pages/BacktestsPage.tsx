import { FlaskConical } from 'lucide-react'

import { PlaceholderPage } from '@/components/layout/PlaceholderPage'

export function BacktestsPage() {
  return (
    <PlaceholderPage
      title="Backtests"
      description="Reproducible backtests and walk-forward runs — every number can be re-derived."
      icon={FlaskConical}
      emptyTitle="No backtest runs yet"
      emptyDescription="Runs are listed with the exact data range, configuration and code version used, alongside their results."
      planned={[
        'Equity and drawdown curves',
        'Walk-forward, out-of-sample splits',
        'Trade statistics and costs',
        'Side-by-side run comparison',
      ]}
    />
  )
}
