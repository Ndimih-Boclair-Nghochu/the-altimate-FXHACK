import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { KillSwitchButton } from './KillSwitchButton'

function setup(onConfirm?: () => void) {
  const user = userEvent.setup()
  render(<KillSwitchButton onConfirm={onConfirm} />)
  const trigger = screen.getByRole('button', { name: /kill switch/i })
  return { user, trigger }
}

describe('KillSwitchButton', () => {
  it('opens a confirmation dialog focused on Cancel', async () => {
    const { user, trigger } = setup()

    await user.click(trigger)

    const dialog = screen.getByRole('alertdialog', { name: 'Engage the kill switch?' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).toHaveAccessibleDescription(/closes every open position/i)
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()
    expect(screen.getByText(/preview only/i)).toBeInTheDocument()
  })

  it('can be cancelled without engaging, returning focus to the trigger', async () => {
    const onConfirm = vi.fn()
    const { user, trigger } = setup(onConfirm)

    await user.click(trigger)
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(onConfirm).not.toHaveBeenCalled()
    expect(trigger).toHaveFocus()
  })

  it('is cancelled by Escape', async () => {
    const onConfirm = vi.fn()
    const { user, trigger } = setup(onConfirm)

    await user.click(trigger)
    await user.keyboard('{Escape}')

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('keeps keyboard focus inside the dialog', async () => {
    const { user, trigger } = setup()

    await user.click(trigger)
    const dialog = screen.getByRole('alertdialog')
    await user.tab()
    await user.tab()
    await user.tab()

    expect(dialog).toContainElement(document.activeElement as HTMLElement)
  })

  it('calls onConfirm only after explicit confirmation', async () => {
    const onConfirm = vi.fn()
    const { user, trigger } = setup(onConfirm)

    await user.click(trigger)
    await user.click(screen.getByRole('button', { name: /flatten & halt trading/i }))

    expect(onConfirm).toHaveBeenCalledOnce()
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })
})
