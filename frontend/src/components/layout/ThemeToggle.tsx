import { Moon, Sun } from 'lucide-react'

import { Button, Tooltip } from '@/components/ui'
import { useThemeStore } from '@/stores/theme'

export function ThemeToggle() {
  const resolved = useThemeStore((s) => s.resolved)
  const toggle = useThemeStore((s) => s.toggle)
  const label = resolved === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'

  return (
    <Tooltip content={label} side="bottom" align="end" describe={false}>
      <Button variant="ghost" size="icon-sm" aria-label={label} onClick={toggle}>
        {resolved === 'dark' ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
      </Button>
    </Tooltip>
  )
}
