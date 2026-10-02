import { Monitor, Moon, Settings, Sun } from 'lucide-react'

import { PlaceholderPage } from '@/components/layout/PlaceholderPage'
import {
  Card,
  CardBody,
  CardHeader,
  SegmentedControl,
  type SegmentedOption,
  Switch,
} from '@/components/ui'
import { type ResolvedTheme, useThemeStore } from '@/stores/theme'

const THEME_OPTIONS: readonly SegmentedOption<ResolvedTheme>[] = [
  {
    value: 'light',
    label: (
      <>
        <Sun aria-hidden="true" />
        Light
      </>
    ),
  },
  {
    value: 'dark',
    label: (
      <>
        <Moon aria-hidden="true" />
        Dark
      </>
    ),
  },
]

function AppearanceCard() {
  const preference = useThemeStore((s) => s.preference)
  const resolved = useThemeStore((s) => s.resolved)
  const setPreference = useThemeStore((s) => s.setPreference)
  const followSystem = preference === 'system'

  return (
    <Card>
      <CardHeader title="Appearance" description="Stored in this browser only." />
      <CardBody className="space-y-5">
        <Switch
          label="Match system theme"
          description="Follow your operating system’s light or dark setting."
          checked={followSystem}
          onCheckedChange={(checked) => {
            setPreference(checked ? 'system' : resolved)
          }}
        />
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="space-y-0.5">
            <p className="text-sm font-medium text-fg">Theme</p>
            <p className="text-[0.8125rem] text-fg-muted">
              {followSystem ? (
                <span className="inline-flex items-center gap-1.5">
                  <Monitor className="size-3.5" aria-hidden="true" />
                  Using system: {resolved}
                </span>
              ) : (
                'Pinned for this browser.'
              )}
            </p>
          </div>
          <SegmentedControl
            label="Theme"
            value={resolved}
            options={THEME_OPTIONS}
            onValueChange={setPreference}
          />
        </div>
      </CardBody>
    </Card>
  )
}

export function SettingsPage() {
  return (
    <PlaceholderPage
      title="Settings"
      description="Broker connection, trading mode and risk parameters."
      icon={Settings}
      emptyTitle="System settings arrive with the engine API"
      emptyDescription="Configuration is read from the server. Secrets such as broker API keys never leave the backend and are never shown here."
      planned={[
        'Broker connection status',
        'Trading mode and live-trading guard',
        'Risk parameter review',
        'Notification preferences',
      ]}
    >
      <AppearanceCard />
    </PlaceholderPage>
  )
}
