import {
  ArrowLeftRight,
  BrainCircuit,
  FlaskConical,
  Layers,
  LayoutDashboard,
  type LucideIcon,
  Settings,
  ShieldCheck,
} from 'lucide-react'

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  /** Match the path exactly (needed for the index route). */
  end?: boolean
}

export const PRIMARY_NAV: readonly NavItem[] = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/trades', label: 'Trades', icon: ArrowLeftRight },
  { to: '/strategies', label: 'Strategies', icon: Layers },
  { to: '/learning', label: 'Learning', icon: BrainCircuit },
  { to: '/risk', label: 'Risk', icon: ShieldCheck },
  { to: '/backtests', label: 'Backtests', icon: FlaskConical },
]

export const SECONDARY_NAV: readonly NavItem[] = [
  { to: '/settings', label: 'Settings', icon: Settings },
]

export const ALL_NAV: readonly NavItem[] = [...PRIMARY_NAV, ...SECONDARY_NAV]
