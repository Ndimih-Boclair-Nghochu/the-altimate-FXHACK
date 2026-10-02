import { Outlet } from 'react-router'

import { Drawer } from '@/components/ui'
import { useUiStore } from '@/stores/ui'

import { Brand } from './LogoMark'
import { Sidebar } from './Sidebar'
import { SidebarNav } from './SidebarNav'
import { TopBar } from './TopBar'

export function AppShell() {
  const mobileNavOpen = useUiStore((s) => s.mobileNavOpen)
  const setMobileNavOpen = useUiStore((s) => s.setMobileNavOpen)

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-background text-fg">
      <a
        href="#main"
        className="fixed top-2 left-2 z-[70] -translate-y-16 rounded-lg bg-accent-solid px-3 py-2 text-sm font-medium text-on-accent transition-transform focus:translate-y-0"
      >
        Skip to content
      </a>

      <TopBar />

      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main id="main" tabIndex={-1} className="min-w-0 flex-1 overflow-y-auto outline-none">
          <div className="mx-auto w-full max-w-[90rem] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
            <Outlet />
          </div>
        </main>
      </div>

      <Drawer
        open={mobileNavOpen}
        onOpenChange={setMobileNavOpen}
        label="Navigation"
        header={<Brand />}
      >
        <SidebarNav
          className="px-4 py-4"
          onNavigate={() => {
            setMobileNavOpen(false)
          }}
        />
      </Drawer>
    </div>
  )
}
