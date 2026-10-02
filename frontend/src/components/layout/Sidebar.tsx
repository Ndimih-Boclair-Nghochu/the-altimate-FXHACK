import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'

import { Button, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { useUiStore } from '@/stores/ui'

import { SidebarNav } from './SidebarNav'

/** Desktop sidebar (md and up). Collapses to an icon rail; the choice is remembered. */
export function Sidebar() {
  const collapsed = useUiStore((s) => s.sidebarCollapsed)
  const toggleSidebar = useUiStore((s) => s.toggleSidebar)
  const label = collapsed ? 'Expand sidebar' : 'Collapse sidebar'

  return (
    <aside
      aria-label="Sidebar"
      data-collapsed={collapsed}
      className={cn(
        'hidden shrink-0 flex-col border-r border-border bg-background transition-[width] duration-200 ease-out md:flex',
        collapsed ? 'w-[3.75rem]' : 'w-60',
      )}
    >
      <SidebarNav
        collapsed={collapsed}
        className={cn('overflow-y-auto py-4', collapsed ? 'px-3' : 'px-4')}
      />
      <div
        className={cn(
          'flex h-12 shrink-0 items-center border-t border-border',
          collapsed ? 'justify-center' : 'justify-between pr-2 pl-4',
        )}
      >
        {!collapsed ? (
          <span className="text-2xs text-fg-subtle tabular-nums">UI v{__APP_VERSION__}</span>
        ) : null}
        <Tooltip content={label} side="right" describe={false}>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={label}
            aria-expanded={!collapsed}
            onClick={toggleSidebar}
          >
            {collapsed ? (
              <PanelLeftOpen aria-hidden="true" />
            ) : (
              <PanelLeftClose aria-hidden="true" />
            )}
          </Button>
        </Tooltip>
      </div>
    </aside>
  )
}
