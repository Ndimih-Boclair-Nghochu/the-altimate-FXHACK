import { create } from 'zustand'

import { readStorage, writeStorage } from '@/lib/storage'

export const SIDEBAR_STORAGE_KEY = 'altimate-fx.sidebar-collapsed'

interface UiState {
  /** Desktop sidebar collapsed to an icon rail (persisted). */
  sidebarCollapsed: boolean
  /** Mobile navigation drawer open. */
  mobileNavOpen: boolean
  toggleSidebar: () => void
  setMobileNavOpen: (open: boolean) => void
}

export const useUiStore = create<UiState>()((set, get) => ({
  sidebarCollapsed: readStorage(SIDEBAR_STORAGE_KEY) === 'true',
  mobileNavOpen: false,
  toggleSidebar: () => {
    const sidebarCollapsed = !get().sidebarCollapsed
    writeStorage(SIDEBAR_STORAGE_KEY, String(sidebarCollapsed))
    set({ sidebarCollapsed })
  },
  setMobileNavOpen: (mobileNavOpen) => {
    set({ mobileNavOpen })
  },
}))
