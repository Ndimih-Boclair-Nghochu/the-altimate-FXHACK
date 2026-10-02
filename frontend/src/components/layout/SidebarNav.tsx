import { NavLink } from 'react-router'

import { Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'

import { type NavItem, PRIMARY_NAV, SECONDARY_NAV } from './nav'

interface SidebarLinkProps {
  item: NavItem
  collapsed: boolean
  onNavigate?: () => void
}

function SidebarLink({ item, collapsed, onNavigate }: SidebarLinkProps) {
  const Icon = item.icon
  const link = (
    <NavLink
      to={item.to}
      end={item.end}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          'group relative flex h-9 items-center gap-3 rounded-lg text-sm font-medium transition-colors duration-150',
          collapsed ? 'w-9 justify-center' : 'w-full px-2.5',
          isActive
            ? 'bg-surface-muted text-fg before:absolute before:top-2 before:bottom-2 before:-left-2 before:w-0.5 before:rounded-full before:bg-accent'
            : 'text-fg-muted hover:bg-surface-muted/70 hover:text-fg',
        )
      }
    >
      {({ isActive }) => (
        <>
          <Icon
            className={cn(
              'size-[1.125rem] shrink-0 transition-colors',
              isActive ? 'text-accent' : 'text-fg-subtle group-hover:text-fg-muted',
            )}
            aria-hidden="true"
          />
          <span className={collapsed ? 'sr-only' : 'truncate'}>{item.label}</span>
        </>
      )}
    </NavLink>
  )

  return (
    <li className="flex">
      {collapsed ? (
        <Tooltip content={item.label} side="right" describe={false}>
          {link}
        </Tooltip>
      ) : (
        link
      )}
    </li>
  )
}

interface SidebarNavProps {
  collapsed?: boolean
  /** Called after a link is chosen (closes the mobile drawer). */
  onNavigate?: () => void
  className?: string
}

/** Primary navigation, shared by the desktop sidebar and the mobile drawer. */
export function SidebarNav({ collapsed = false, onNavigate, className }: SidebarNavProps) {
  return (
    <nav aria-label="Primary" className={cn('flex min-h-0 flex-1 flex-col', className)}>
      {!collapsed ? (
        <p className="px-2.5 pb-2 text-2xs font-medium tracking-wider text-fg-subtle uppercase">
          Workspace
        </p>
      ) : null}
      <ul className={cn('flex flex-col gap-0.5', collapsed && 'items-center')}>
        {PRIMARY_NAV.map((item) => (
          <SidebarLink key={item.to} item={item} collapsed={collapsed} onNavigate={onNavigate} />
        ))}
      </ul>
      <ul className={cn('mt-auto flex flex-col gap-0.5 pt-4', collapsed && 'items-center')}>
        {SECONDARY_NAV.map((item) => (
          <SidebarLink key={item.to} item={item} collapsed={collapsed} onNavigate={onNavigate} />
        ))}
      </ul>
    </nav>
  )
}
