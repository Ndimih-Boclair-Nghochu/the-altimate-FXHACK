import { ArrowLeftRight } from 'lucide-react'

import { PlaceholderPage } from '@/components/layout/PlaceholderPage'

export function TradesPage() {
  return (
    <PlaceholderPage
      title="Trades"
      description="The trade journal: every order, fill and closed trade the engine has made."
      icon={ArrowLeftRight}
      emptyTitle="No trades to show yet"
      emptyDescription="Once the trading engine is connected, each trade appears here straight from the journal — nothing is estimated or back-filled."
      planned={[
        'Entry, exit, size and realised P&L',
        'R-multiple, fees and slippage',
        'Strategy and market-regime tags',
        'Filters, sorting and CSV export',
      ]}
    />
  )
}
