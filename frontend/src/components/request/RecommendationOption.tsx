import { ChevronDown, Database, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { SourceBadge } from '@/components/common/badges'
import { ConfidenceMeter } from '@/components/common/ConfidenceMeter'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { CaseActions } from '@/hooks/useCaseActions'
import { formatInr } from '@/lib/format'
import { approvalLabel, timing } from '@/lib/recommendation'
import type { Recommendation, RequestDetail } from '@/lib/types'
import { cn } from '@/lib/utils'
import { ForwardDialog } from './ForwardDialog'

function source(r: Recommendation) {
  return r.created_by === 'human' ? 'human' : r.model === 'fallback' ? 'fallback' : 'agent'
}

/** The button that moves an option forward: send for approval, or start when none is needed. */
export function ChooseButton({
  c,
  r,
  actions,
  primary,
}: {
  c: RequestDetail
  r: Recommendation
  actions: CaseActions
  primary?: boolean
}) {
  const [forwarding, setForwarding] = useState(false)
  if (!c.allowed_actions.includes('select_recommendation') || r.status !== 'proposed') return null
  return (
    <>
      <Button
        size="sm"
        variant={primary ? 'primary' : 'outline'}
        loading={!r.requires_approval && actions.select.isPending}
        onClick={() =>
          r.requires_approval ? setForwarding(true) : actions.select.mutate({ recId: r.id })
        }
      >
        {r.requires_approval ? 'Choose & send for approval' : 'Choose & start work'}
      </Button>
      <ForwardDialog c={c} r={r} open={forwarding} onOpenChange={setForwarding} actions={actions} />
    </>
  )
}

/** One row of the comparison: the facts side by side, details on demand. */
export function OptionRow({
  c,
  r,
  actions,
  top,
}: {
  c: RequestDetail
  r: Recommendation
  actions: CaseActions
  top: boolean
}) {
  const [open, setOpen] = useState(false)
  const inactive = r.status !== 'proposed' && r.status !== 'selected'
  const when = timing(r, c.deadline_at)
  return (
    <li className={cn('border-b border-line last:border-0', inactive && 'opacity-55')}>
      <div className="grid grid-cols-[2rem_minmax(0,2.4fr)_minmax(0,1.6fr)_6rem_6rem_minmax(0,1.3fr)] items-center gap-3 px-4 py-3 text-sm">
        <span
          className={cn(
            'flex size-7 items-center justify-center font-bold',
            top ? 'bg-accent' : 'bg-page',
          )}
        >
          {r.created_by === 'human' ? '★' : r.rank}
        </span>
        <div className="min-w-0">
          <p className="font-bold">{r.title}</p>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {top && <Badge tone="dark">AI pick</Badge>}
            {r.status !== 'proposed' && <Badge tone="neutral">{r.status}</Badge>}
            <SourceBadge source={source(r)} />
          </div>
        </div>
        <p className="text-ink-muted">{r.risk_reduction || '—'}</p>
        <p className="font-bold tabular-nums">{formatInr(r.estimated_cost_inr)}</p>
        <p>
          {r.estimated_lead_time_days} day{r.estimated_lead_time_days === 1 ? '' : 's'}
          {when && (
            <span className={cn('block text-xs', when === 'late' ? 'text-bad' : 'text-ok')}>
              {when === 'late' ? 'after deadline' : 'before deadline'}
            </span>
          )}
        </p>
        <p className="text-xs">{approvalLabel(r)}</p>
      </div>
      <div className="flex flex-wrap items-center gap-3 px-4 pb-3 pl-[3.75rem]">
        <ChooseButton c={c} r={r} actions={actions} primary={top} />
        <button
          type="button"
          className="inline-flex items-center gap-1 text-xs font-bold"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          <ChevronDown className={cn('size-3.5 transition-transform', open && 'rotate-180')} />
          {open ? 'Hide details' : 'Why & details'}
        </button>
      </div>
      {open && <OptionDetails r={r} />}
    </li>
  )
}

function OptionDetails({ r }: { r: Recommendation }) {
  return (
    <div className="mx-4 mb-3 ml-[3.75rem] space-y-2 bg-page px-3 py-2 text-sm">
      <p>{r.description}</p>
      {r.rationale && (
        <p>
          <b>Why: </b>
          {r.rationale}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-ink-muted">Confidence</span>
        <ConfidenceMeter value={r.confidence} compact className="w-40" />
      </div>
      {r.requires_approval && (
        <p className="flex items-start gap-1.5 text-xs">
          <ShieldCheck className="mt-0.5 size-3.5 shrink-0" />
          <span>
            <b>Approval needed because: </b>
            {r.approval_reasons.join(' · ')}
          </span>
        </p>
      )}
      {r.override_reason && (
        <p className="text-xs">
          <b>Override reason: </b>
          {r.override_reason}
        </p>
      )}
      {r.evidence.length > 0 && (
        <p className="flex flex-wrap items-center gap-1 text-xs">
          <Database className="size-3.5" /> Based on:
          {r.evidence.map((e) => (
            <Badge key={e} tone="neutral" className="normal-case">
              {e}
            </Badge>
          ))}
        </p>
      )}
    </div>
  )
}
