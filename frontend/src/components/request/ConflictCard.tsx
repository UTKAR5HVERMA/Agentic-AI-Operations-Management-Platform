import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/form'
import type { CaseActions } from '@/hooks/useCaseActions'
import { timeAgo } from '@/lib/format'
import type { Issue } from '@/lib/types'

/** Edge case 2: email vs system of record, side by side. Default = inventory. */
export function ConflictCard({
  issue,
  actions,
  canResolve,
}: {
  issue: Issue
  actions: CaseActions
  canResolve: boolean
}) {
  const [custom, setCustom] = useState('')
  const d = issue.details as {
    email_value?: number
    inventory_value?: number
    location?: string
    inventory_updated_at?: string
  }
  const resolve = (resolution: string, note: string, value?: string) =>
    actions.resolveIssue.mutate({ issueId: issue.id, resolution, note, value })

  return (
    <div className="border-l-4 border-warn bg-white ring-1 ring-line">
      <p className="px-4 pt-3 font-bold">Conflicting quantity available</p>
      <div className="grid grid-cols-2 gap-px bg-line">
        <div className="bg-white px-4 py-3">
          <p className="text-[11px] font-bold tracking-wide text-ink-muted uppercase">Email says</p>
          <p className="text-3xl font-bold tabular-nums">{d.email_value}</p>
          <p className="text-xs text-ink-muted">Stated by the sender</p>
        </div>
        <div className="bg-white px-4 py-3">
          <p className="text-[11px] font-bold tracking-wide text-ink-muted uppercase">
            Inventory system says
          </p>
          <p className="text-3xl font-bold tabular-nums">{d.inventory_value}</p>
          <p className="text-xs text-ink-muted">
            {d.location} · system of record
            {d.inventory_updated_at ? ` · updated ${timeAgo(d.inventory_updated_at)}` : ''}
          </p>
        </div>
      </div>
      {canResolve && (
        <div className="flex flex-wrap items-center gap-2 border-t border-line px-4 py-3">
          <Button
            size="sm"
            variant="primary"
            onClick={() => resolve('use_inventory', 'Inventory is the system of record')}
            loading={actions.resolveIssue.isPending}
          >
            Use inventory
          </Button>
          <Button size="sm" onClick={() => resolve('use_email', 'Sender count verified on site')}>
            Use email
          </Button>
          <Input
            aria-label="Custom value"
            className="w-28"
            type="number"
            min={0}
            placeholder="Value"
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
          />
          <Button
            size="sm"
            variant="ghost"
            disabled={!custom}
            onClick={() => resolve('custom', 'Manually verified count', custom)}
          >
            Enter value
          </Button>
        </div>
      )}
    </div>
  )
}
