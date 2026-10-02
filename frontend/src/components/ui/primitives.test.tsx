import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { Button } from './Button'
import { SegmentedControl } from './SegmentedControl'
import { Switch } from './Switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './Table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from './Tabs'
import { Tooltip } from './Tooltip'

describe('Button', () => {
  it('defaults to type="button" and blocks clicks while loading', async () => {
    const onClick = vi.fn()
    const user = userEvent.setup()
    const { rerender } = render(<Button onClick={onClick}>Save</Button>)
    expect(screen.getByRole('button', { name: 'Save' })).toHaveAttribute('type', 'button')

    rerender(
      <Button onClick={onClick} loading>
        Save
      </Button>,
    )
    const button = screen.getByRole('button', { name: 'Save' })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('aria-busy', 'true')
    await user.click(button)
    expect(onClick).not.toHaveBeenCalled()
  })
})

describe('Switch', () => {
  function Controlled() {
    const [on, setOn] = useState(false)
    return <Switch label="Alerts" description="Notify me" checked={on} onCheckedChange={setOn} />
  }

  it('is a labelled switch that toggles with click and keyboard', async () => {
    const user = userEvent.setup()
    render(<Controlled />)
    const control = screen.getByRole('switch', { name: 'Alerts' })
    expect(control).toHaveAccessibleDescription('Notify me')
    expect(control).toHaveAttribute('aria-checked', 'false')

    await user.click(control)
    expect(control).toHaveAttribute('aria-checked', 'true')

    await user.keyboard(' ')
    expect(control).toHaveAttribute('aria-checked', 'false')
  })
})

describe('Tabs', () => {
  it('links tabs to panels and supports arrow-key navigation', async () => {
    const user = userEvent.setup()
    render(
      <Tabs defaultValue="a">
        <TabsList label="Sections">
          <TabsTrigger value="a">Alpha</TabsTrigger>
          <TabsTrigger value="b">Beta</TabsTrigger>
        </TabsList>
        <TabsContent value="a">Alpha panel</TabsContent>
        <TabsContent value="b">Beta panel</TabsContent>
      </Tabs>,
    )
    const alpha = screen.getByRole('tab', { name: 'Alpha' })
    expect(alpha).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tabpanel', { name: 'Alpha' })).toHaveTextContent('Alpha panel')

    await user.click(alpha)
    await user.keyboard('{ArrowRight}')

    const beta = screen.getByRole('tab', { name: 'Beta' })
    expect(beta).toHaveFocus()
    expect(beta).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tabpanel', { name: 'Beta' })).toHaveTextContent('Beta panel')
    expect(screen.queryByText('Alpha panel')).not.toBeInTheDocument()
  })
})

describe('SegmentedControl', () => {
  it('behaves as a radio group', async () => {
    const user = userEvent.setup()
    function Controlled() {
      const [value, setValue] = useState<'1D' | '1W'>('1D')
      return (
        <SegmentedControl
          label="Range"
          value={value}
          onValueChange={setValue}
          options={[
            { value: '1D', label: '1D' },
            { value: '1W', label: '1W' },
          ]}
        />
      )
    }
    render(<Controlled />)
    expect(screen.getByRole('radiogroup', { name: 'Range' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: '1D' })).toBeChecked()

    await user.click(screen.getByRole('radio', { name: '1W' }))
    expect(screen.getByRole('radio', { name: '1W' })).toBeChecked()

    await user.keyboard('{ArrowLeft}')
    expect(screen.getByRole('radio', { name: '1D' })).toBeChecked()
    expect(screen.getByRole('radio', { name: '1D' })).toHaveFocus()
  })
})

describe('Tooltip', () => {
  it('describes its trigger on keyboard focus and hides on Escape', async () => {
    const user = userEvent.setup()
    render(
      <Tooltip content="Re-check the connection">
        <button type="button">Status</button>
      </Tooltip>,
    )

    await user.tab()
    const tooltip = screen.getByRole('tooltip')
    expect(tooltip).toHaveTextContent('Re-check the connection')
    expect(screen.getByRole('button', { name: 'Status' })).toHaveAccessibleDescription(
      'Re-check the connection',
    )

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })
})

describe('Table', () => {
  it('renders column headers and right-aligns numeric cells', () => {
    render(
      <Table label="Positions">
        <TableHeader>
          <TableRow>
            <TableHead>Pair</TableHead>
            <TableHead numeric>Units</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow>
            <TableCell>EUR/USD</TableCell>
            <TableCell numeric>10,000</TableCell>
          </TableRow>
        </TableBody>
      </Table>,
    )
    expect(screen.getByRole('region', { name: 'Positions' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Units' })).toHaveClass('text-right')
    expect(screen.getByRole('cell', { name: '10,000' })).toHaveClass('numeric', 'text-right')
  })
})
