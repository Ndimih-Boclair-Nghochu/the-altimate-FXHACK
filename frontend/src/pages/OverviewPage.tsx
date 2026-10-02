import { ChartSpline, Info, ShieldCheck } from 'lucide-react'
import { useState } from 'react'

import { PageHeader } from '@/components/layout/PageHeader'
import {
  Badge,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  SegmentedControl,
  type SegmentedOption,
  Skeleton,
  Stat,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/ui'
import { cn } from '@/lib/cn'

/*
 * Stage 0 layout preview. Every figure is a loading placeholder — no numbers are
 * shown until they come from the backend (trade journal / broker) in Stage 6.
 */

type Range = '1D' | '1W' | '1M' | 'ALL'

const RANGES: readonly SegmentedOption<Range>[] = [
  { value: '1D', label: '1D' },
  { value: '1W', label: '1W' },
  { value: '1M', label: '1M' },
  { value: 'ALL', label: 'All' },
]

const STATS = [
  { label: 'Equity', hint: 'Balance + unrealised P&L' },
  { label: 'Today’s P&L', hint: 'Realised + unrealised' },
  { label: 'Open risk', hint: 'At stop, % of equity' },
  { label: 'Drawdown', hint: 'From equity high' },
] as const

const RISK_LIMITS = ['Daily loss limit', 'Weekly loss limit', 'Drawdown breaker'] as const

interface Column {
  label: string
  numeric?: boolean
  width: string
}

const POSITION_COLUMNS: readonly Column[] = [
  { label: 'Instrument', width: 'w-16' },
  { label: 'Side', width: 'w-10' },
  { label: 'Units', numeric: true, width: 'w-14' },
  { label: 'Entry', numeric: true, width: 'w-16' },
  { label: 'Mark', numeric: true, width: 'w-16' },
  { label: 'Stop', numeric: true, width: 'w-16' },
  { label: 'Unrealised P&L', numeric: true, width: 'w-20' },
]

const ORDER_COLUMNS: readonly Column[] = [
  { label: 'Instrument', width: 'w-16' },
  { label: 'Side', width: 'w-10' },
  { label: 'Type', width: 'w-14' },
  { label: 'Units', numeric: true, width: 'w-14' },
  { label: 'Price', numeric: true, width: 'w-16' },
  { label: 'Created', numeric: true, width: 'w-24' },
]

function PreviewNotice() {
  return (
    <div
      role="note"
      className="mb-6 flex items-start gap-3 rounded-xl border border-accent/25 bg-accent/5 px-4 py-3"
    >
      <Info className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden="true" />
      <p className="text-sm text-fg-muted">
        <span className="font-medium text-fg">Layout preview.</span> Live account data is connected
        in Stage 6 — nothing on this page is real trading data yet.
      </p>
    </div>
  )
}

function EquityCard({ className }: { className?: string }) {
  const [range, setRange] = useState<Range>('1M')

  return (
    <Card className={className}>
      <CardHeader
        title="Equity curve"
        description="From the trade journal, marked to market."
        actions={
          <SegmentedControl label="Range" options={RANGES} value={range} onValueChange={setRange} />
        }
      />
      <CardBody>
        <div className="relative h-64 sm:h-72">
          <div
            aria-hidden="true"
            className="absolute inset-0 flex flex-col justify-between pt-1.5 pr-14 pb-7"
          >
            {Array.from({ length: 5 }, (_, i) => (
              <div key={i} className="border-t border-dashed border-border" />
            ))}
          </div>
          <div
            aria-hidden="true"
            className="absolute inset-y-0 right-0 flex w-11 flex-col justify-between pb-6"
          >
            {Array.from({ length: 5 }, (_, i) => (
              <Skeleton key={i} className="h-3 w-full" />
            ))}
          </div>
          <div
            aria-hidden="true"
            className="absolute inset-x-0 bottom-0 flex justify-between pr-14"
          >
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-3 w-9" />
            ))}
          </div>
          <div className="absolute inset-0 flex items-center justify-center pr-14 pb-7">
            <div className="flex max-w-xs flex-col items-center gap-2 rounded-xl bg-surface px-5 py-4 text-center">
              <ChartSpline className="size-5 text-fg-subtle" aria-hidden="true" />
              <p className="text-sm font-medium text-fg">No equity history yet</p>
              <p className="text-xs leading-relaxed text-fg-muted">
                The curve is drawn from recorded trades once the engine is running.
              </p>
            </div>
          </div>
        </div>
      </CardBody>
    </Card>
  )
}

function RiskLimitsCard({ className }: { className?: string }) {
  return (
    <Card className={cn('flex flex-col', className)}>
      <CardHeader title="Risk limits" description="Usage of hard limits, checked on every order." />
      <CardBody className="flex-1 space-y-5">
        {RISK_LIMITS.map((label) => (
          <div key={label}>
            <div className="flex items-baseline justify-between gap-3 text-[0.8125rem]">
              <span className="text-fg-muted">{label}</span>
              <span className="numeric text-fg-subtle">— / —</span>
            </div>
            <div aria-hidden="true" className="mt-2 h-1.5 overflow-hidden rounded-full">
              <Skeleton className="h-full w-full rounded-full" />
            </div>
          </div>
        ))}
      </CardBody>
      <CardFooter className="text-[0.8125rem] text-fg-muted">
        <ShieldCheck className="size-4 text-fg-subtle" aria-hidden="true" />
        Kill switch status unavailable
      </CardFooter>
    </Card>
  )
}

function PlaceholderTable({ columns, caption }: { columns: readonly Column[]; caption: string }) {
  return (
    <Table containerClassName="max-h-80">
      <TableHeader>
        <TableRow>
          {columns.map((column) => (
            <TableHead key={column.label} numeric={column.numeric}>
              {column.label}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody aria-hidden="true">
        {Array.from({ length: 4 }, (_, row) => (
          <TableRow key={row} className="opacity-70">
            {columns.map((column) => (
              <TableCell key={column.label} numeric={column.numeric}>
                <Skeleton className={`h-3.5 ${column.width} ${column.numeric ? 'ml-auto' : ''}`} />
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
      <TableCaption className="mb-4 px-5">{caption}</TableCaption>
    </Table>
  )
}

function PositionsCard({ className }: { className?: string }) {
  return (
    <Card className={className}>
      <Tabs defaultValue="positions">
        <TabsList label="Positions and orders" className="px-5 pt-2">
          <TabsTrigger value="positions">Open positions</TabsTrigger>
          <TabsTrigger value="orders">Working orders</TabsTrigger>
        </TabsList>
        <TabsContent value="positions">
          <PlaceholderTable
            columns={POSITION_COLUMNS}
            caption="Open positions stream here in real time once the engine is connected."
          />
        </TabsContent>
        <TabsContent value="orders">
          <PlaceholderTable
            columns={ORDER_COLUMNS}
            caption="Pending orders, with their stops and targets, appear here."
          />
        </TabsContent>
      </Tabs>
    </Card>
  )
}

export function OverviewPage() {
  return (
    <>
      <PageHeader
        title="Overview"
        description="Account health, exposure and performance at a glance."
        badge={<Badge variant="accent">Preview</Badge>}
      />
      <PreviewNotice />

      <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
        {STATS.map((stat) => (
          <Card key={stat.label} className="p-4 sm:p-5">
            <Stat label={stat.label} value={null} hint={stat.hint} loading />
          </Card>
        ))}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <EquityCard className="lg:col-span-2" />
        <RiskLimitsCard />
      </div>

      <PositionsCard className="mt-4" />
    </>
  )
}
