import {
  ArrowLeft,
  CheckCircle2,
  MessageSquarePlus,
  PauseCircle,
  PlayCircle,
  RefreshCw,
  Undo2,
  XCircle,
  Zap,
} from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { PriorityBadge, StatusBadge } from '@/components/common/badges'
import { ConfidenceMeter } from '@/components/common/ConfidenceMeter'
import { ReasonDialog } from '@/components/common/ReasonDialog'
import { SlaTimer } from '@/components/common/SlaTimer'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/form'
import type { CaseActions } from '@/hooks/useCaseActions'
import { formatIst, titleCase } from '@/lib/format'
import { CATEGORY_LABEL, STATUS_LABEL } from '@/lib/labels'
import type { RequestDetail, Status } from '@/lib/types'
import { ClarifyButton } from './ClarifyButton'
import { EventDialog } from './EventDialog'

const TERMINAL = new Set<Status>(['CLOSED', 'CANCELLED', 'DUPLICATE', 'RESOLVED'])
type Open = null | 'info' | 'cancel' | 'hold' | 'event'

export function RequestHeader({ c, actions }: { c: RequestDetail; actions: CaseActions }) {
  const [open, setOpen] = useState<Open>(null)
  const [info, setInfo] = useState('')
  const can = (a: string) => c.allowed_actions.includes(a)
  const close = () => setOpen(null)
  const resumeTo = c.previous_status

  return (
    <div className="mb-4 border-b border-line pb-4">
      <Link
        to="/requests"
        className="mb-3 inline-flex items-center gap-1 text-xs font-bold text-ink-muted hover:text-ink"
      >
        <ArrowLeft className="size-3.5" /> All requests
      </Link>
      <div>
        <div className="min-w-0">
          <p className="text-xs font-bold tracking-widest text-ink-muted uppercase">
            {c.ref} · {CATEGORY_LABEL[c.category]} · {titleCase(c.channel)} · {c.region}
          </p>
          <h1 className="mt-1 border-l-4 border-accent pl-3 text-2xl leading-tight">{c.subject}</h1>
          <div className="mt-3 flex flex-wrap items-center gap-3 pl-4">
            <StatusBadge status={c.status} />
            <PriorityBadge priority={c.priority} />
            {c.degraded && (
              <Badge tone="warn">
                <Zap /> Degraded ({c.degraded_reasons.join(', ')})
              </Badge>
            )}
            <span className="text-xs text-ink-muted">Deadline</span>
            <SlaTimer target={c.deadline_at} done={TERMINAL.has(c.status)} />
            <span className="text-xs text-ink-muted">Confidence</span>
            <ConfidenceMeter
              value={c.overall_confidence}
              breakdown={c.confidence_breakdown}
              className="w-56"
            />
          </div>
          <p className="mt-2 pl-4 text-xs text-ink-muted">
            Received {formatIst(c.received_at)} from {c.sender.name ?? c.sender.email ?? 'unknown'}
          </p>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2 pl-4 empty:hidden">
          <ClarifyButton c={c} actions={actions} />
          {can('provide_info') && (
            <Button size="sm" onClick={() => setOpen('info')}>
              <MessageSquarePlus /> Add info
            </Button>
          )}
          {can('reanalyze') && (
            <Button
              size="sm"
              onClick={() => actions.reanalyze.mutate(undefined)}
              loading={actions.reanalyze.isPending}
            >
              <RefreshCw /> Re-analyze
            </Button>
          )}
          {can('add_event') && (
            <Button size="sm" onClick={() => setOpen('event')}>
              <Zap /> Report change
            </Button>
          )}
          {can('resolve') && (
            <Button
              size="sm"
              variant="primary"
              onClick={() =>
                actions.transition.mutate({ to: 'RESOLVED', reason: 'Action completed' })
              }
            >
              <CheckCircle2 /> Mark resolved
            </Button>
          )}
          {can('close') && (
            <Button
              size="sm"
              variant="primary"
              onClick={() =>
                actions.transition.mutate({ to: 'CLOSED', reason: 'Confirmed resolved' })
              }
            >
              <CheckCircle2 /> Close
            </Button>
          )}
          {can('reopen') && (
            <Button
              size="sm"
              onClick={() => actions.transition.mutate({ to: 'IN_PROGRESS', reason: 'Reopened' })}
            >
              <Undo2 /> Reopen
            </Button>
          )}
          {can('hold') && (
            <Button size="sm" onClick={() => setOpen('hold')}>
              <PauseCircle /> Hold
            </Button>
          )}
          {can('resume') && resumeTo && (
            <Button size="sm" onClick={() => actions.transition.mutate({ to: resumeTo })}>
              <PlayCircle /> Resume ({STATUS_LABEL[resumeTo]})
            </Button>
          )}
          {can('cancel') && (
            <Button size="sm" variant="danger" onClick={() => setOpen('cancel')}>
              <XCircle /> Cancel
            </Button>
          )}
        </div>
      </div>

      <Dialog
        open={open === 'info'}
        onOpenChange={(o) => !o && close()}
        title="Add information"
        description="Appended to the request; all agents re-run on the updated text."
        footer={
          <Button
            variant="primary"
            disabled={!info.trim()}
            loading={actions.provideInfo.isPending}
            onClick={() =>
              actions.provideInfo.mutate(info, {
                onSuccess: () => {
                  setInfo('')
                  close()
                },
              })
            }
          >
            Add & re-analyze
          </Button>
        }
      >
        <Textarea
          aria-label="Additional information"
          className="min-h-40"
          value={info}
          onChange={(e) => setInfo(e.target.value)}
          placeholder="e.g. Supplier is DisplayCo; needed by 10 Nov."
        />
      </Dialog>
      <ReasonDialog
        open={open === 'cancel'}
        onOpenChange={(o) => !o && close()}
        title={`Cancel ${c.ref}?`}
        description="Pending approvals are cancelled, reserved stock is released and notices are drafted."
        confirmLabel="Cancel request"
        destructive
        pending={actions.cancel.isPending}
        onConfirm={(r) => actions.cancel.mutate(r, { onSuccess: close })}
      />
      <ReasonDialog
        open={open === 'hold'}
        onOpenChange={(o) => !o && close()}
        title="Put on hold"
        confirmLabel="Put on hold"
        pending={actions.transition.isPending}
        onConfirm={(r) =>
          actions.transition.mutate({ to: 'ON_HOLD', reason: r }, { onSuccess: close })
        }
      />
      <EventDialog open={open === 'event'} onOpenChange={(o) => !o && close()} actions={actions} />
    </div>
  )
}
