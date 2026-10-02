import { Menu } from 'lucide-react'
import { Link } from 'react-router'

import { Button } from '@/components/ui'
import { useHealthQuery } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

import { connectionStateFrom } from './connection'
import { ConnectionStatus } from './ConnectionStatus'
import { KillSwitchButton } from './KillSwitchButton'
import { Brand } from './LogoMark'
import { ModeBadge } from './ModeBadge'
import { ThemeToggle } from './ThemeToggle'

export function TopBar() {
  const health = useHealthQuery()
  const mobileNavOpen = useUiStore((s) => s.mobileNavOpen)
  const setMobileNavOpen = useUiStore((s) => s.setMobileNavOpen)

  return (
    <header className="relative z-20 flex h-14 shrink-0 items-center gap-2 border-b border-border bg-background/85 px-3 backdrop-blur-md sm:gap-3 sm:px-4">
      <Button
        variant="ghost"
        size="icon-sm"
        className="-ml-1 md:hidden"
        aria-label="Open navigation"
        aria-expanded={mobileNavOpen}
        onClick={() => {
          setMobileNavOpen(true)
        }}
      >
        <Menu aria-hidden="true" />
      </Button>

      <Link to="/" className="rounded-md" aria-label="Altimate FX home">
        <Brand className="[&>span:last-child]:max-[359px]:hidden" />
      </Link>

      <span aria-hidden="true" className="hidden h-5 w-px bg-border sm:block" />
      <ModeBadge mode={health.data?.mode} />

      <div className="ml-auto flex items-center gap-1 sm:gap-2">
        <ConnectionStatus
          state={connectionStateFrom(health)}
          version={health.data?.version}
          error={health.error?.message}
          onRetry={() => {
            void health.refetch()
          }}
        />
        <ThemeToggle />
        <span aria-hidden="true" className="mx-0.5 hidden h-5 w-px bg-border sm:block" />
        <KillSwitchButton />
      </div>
    </header>
  )
}
