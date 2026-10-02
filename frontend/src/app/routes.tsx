import { type RouteObject } from 'react-router'

import { AppShell } from '@/components/layout/AppShell'
import { BacktestsPage } from '@/pages/BacktestsPage'
import { LearningPage } from '@/pages/LearningPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { OverviewPage } from '@/pages/OverviewPage'
import { RiskPage } from '@/pages/RiskPage'
import { RouteErrorPage } from '@/pages/RouteErrorPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { StrategiesPage } from '@/pages/StrategiesPage'
import { TradesPage } from '@/pages/TradesPage'

/** Route table, shared by the browser router and tests (memory router). */
export const routes: RouteObject[] = [
  {
    path: '/',
    element: <AppShell />,
    children: [
      {
        // Pathless layout route: page errors render inside the shell.
        errorElement: <RouteErrorPage />,
        children: [
          { index: true, element: <OverviewPage /> },
          { path: 'trades', element: <TradesPage /> },
          { path: 'strategies', element: <StrategiesPage /> },
          { path: 'learning', element: <LearningPage /> },
          { path: 'risk', element: <RiskPage /> },
          { path: 'backtests', element: <BacktestsPage /> },
          { path: 'settings', element: <SettingsPage /> },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
]
