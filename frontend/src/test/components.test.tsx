import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Link, MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { StatusBadge } from '@/components/common/badges'
import { ConfidenceMeter } from '@/components/common/ConfidenceMeter'
import { ReasonDialog } from '@/components/common/ReasonDialog'
import { Button } from '@/components/ui/button'
import { confidenceLevel } from '@/lib/confidence'
import { formatInr } from '@/lib/format'
import { requesterStatus } from '@/lib/labels'

describe('ConfidenceMeter', () => {
  it.each([
    [0.85, 'High'],
    [0.8, 'High'],
    [0.79, 'Needs review'],
    [0.5, 'Needs review'],
    [0.49, 'Low'],
  ])('maps %s to %s', (value, label) => {
    expect(confidenceLevel(value).label).toBe(label)
  })

  it('renders the percentage and band', () => {
    render(<ConfidenceMeter value={0.548} />)
    expect(screen.getByLabelText('Confidence 55% Needs review')).toBeInTheDocument()
  })
})

describe('ReasonDialog', () => {
  it('requires at least 5 characters before confirming', async () => {
    const onConfirm = vi.fn()
    const user = userEvent.setup()
    render(
      <ReasonDialog
        open
        onOpenChange={() => {}}
        title="Reject"
        confirmLabel="Reject"
        onConfirm={onConfirm}
      />,
    )
    const confirm = screen.getByRole('button', { name: 'Reject' })
    expect(confirm).toBeDisabled()

    await user.type(screen.getByRole('textbox'), 'no')
    expect(confirm).toBeDisabled()

    await user.type(screen.getByRole('textbox'), ' budget')
    expect(confirm).toBeEnabled()
    await user.click(confirm)
    expect(onConfirm).toHaveBeenCalledWith('no budget')
  })
})

describe('StatusBadge', () => {
  it('shows a readable label', () => {
    render(<StatusBadge status="PENDING_APPROVAL" />)
    expect(screen.getByText('Pending approval')).toBeInTheDocument()
  })

  it('strikes through cancelled cases', () => {
    render(<StatusBadge status="CANCELLED" />)
    expect(screen.getByText('Cancelled')).toHaveClass('line-through')
  })
})

describe('formatInr', () => {
  it('uses Indian digit grouping', () => {
    expect(formatInr(560000)).toBe('₹5,60,000')
  })
})

describe('Button', () => {
  it('renders a single link child with asChild (Radix Slot)', () => {
    render(
      <MemoryRouter>
        <Button asChild>
          <Link to="/requests/new">New request</Link>
        </Button>
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: 'New request' })).toHaveAttribute(
      'href',
      '/requests/new',
    )
  })
})

describe('requesterStatus', () => {
  it.each([
    ['NEW', null, 'Submitted'],
    ['PENDING_REVIEW', null, 'Under review'],
    ['NEEDS_INFO', null, 'More information needed'],
    ['PENDING_APPROVAL', 'ops_manager', 'Regional Manager approval pending'],
    ['PENDING_APPROVAL', 'admin', 'Director approval pending'],
    ['ESCALATED', 'admin', 'Director approval pending'],
    ['IN_PROGRESS', null, 'Approved – action in progress'],
    ['DUPLICATE', null, 'Merged with an existing request'],
  ] as const)('%s (%s) → %s', (status, role, label) => {
    expect(requesterStatus(status, role)).toBe(label)
  })
})
