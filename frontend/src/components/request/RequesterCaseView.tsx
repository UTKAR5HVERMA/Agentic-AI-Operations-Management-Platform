import { ArrowLeft, Check, Mail, XCircle } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { RequesterStatusBadge } from '@/components/common/badges'
import { ReasonDialog } from '@/components/common/ReasonDialog'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { useCaseActions } from '@/hooks/useCaseActions'
import { formatIst } from '@/lib/format'
import { FIELD_LABEL, requesterStatus } from '@/lib/labels'
import type { RequestDetail, Status } from '@/lib/types'
import { cn } from '@/lib/utils'
import { RequesterReply } from './RequesterReply'

const STEPS = ['Submitted', 'Under review', 'Approval', 'Action in progress', 'Resolved']
const STEP_OF: Partial<Record<Status, number>> = {
  NEW: 0,
  ANALYZING: 1,
  PENDING_REVIEW: 1,
  NEEDS_INFO: 1,
  REJECTED: 1,
  ON_HOLD: 1,
  PENDING_APPROVAL: 2,
  ESCALATED: 2,
  APPROVED: 3,
  IN_PROGRESS: 3,
  RESOLVED: 4,
  CLOSED: 4,
}

function Progress({ c }: { c: RequestDetail }) {
  const current = STEP_OF[c.status]
  if (current === undefined) return null // cancelled / merged: the status badge says it all
  return (
    <ol className="flex flex-wrap items-center gap-2" aria-label="Request progress">
      {STEPS.map((step, i) => (
        <li key={step} className="flex items-center gap-2">
          <span
            className={cn(
              'flex size-6 items-center justify-center rounded-full text-xs font-bold',
              i < current && 'bg-ink text-accent',
              i === current && 'bg-accent text-ink ring-2 ring-ink',
              i > current && 'bg-page text-ink-muted ring-1 ring-line',
            )}
          >
            {i < current ? <Check className="size-3.5" /> : i + 1}
          </span>
          <span className={cn('text-sm', i <= current ? 'font-bold' : 'text-ink-muted')}>
            {i === 2 && current === 2 ? requesterStatus(c.status, c.awaiting_role) : step}
          </span>
          {i < STEPS.length - 1 && <span className="mx-1 h-px w-6 bg-line-strong" />}
        </li>
      ))}
    </ol>
  )
}

/** Requester view: track the request in business terms; no internal AI or cost details. */
export function RequesterCaseView({ c }: { c: RequestDetail }) {
  const actions = useCaseActions(c)
  const [cancelling, setCancelling] = useState(false)
  const can = (a: string) => c.allowed_actions.includes(a)
  // The conversation: team messages to the requester (emailed, or in-app when email failed)
  // and the requester's own replies, oldest first.
  const thread = c.communications.filter(
    (m) =>
      m.type === 'requester_reply' ||
      ((m.status === 'sent' || m.delivered_via === 'in_app') &&
        c.sender.email &&
        m.to.includes(c.sender.email)),
  )
  const missing = c.missing_fields.map((f) => FIELD_LABEL[f] ?? f)
  // Reply whenever the team has asked something (not only in "needs info": a clarification can
  // be sent while the case is still under review).
  const asked = thread.some((m) => m.type === 'clarification') || c.status === 'NEEDS_INFO'

  return (
    <div className="space-y-5">
      <Link
        to="/requests"
        className="inline-flex items-center gap-1 text-xs font-bold text-ink-muted hover:text-ink"
      >
        <ArrowLeft className="size-3.5" /> My requests
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold tracking-widest text-ink-muted uppercase">{c.ref}</p>
          <h1 className="mt-1 border-l-4 border-accent pl-3 text-2xl">{c.subject}</h1>
          <p className="mt-2 pl-4 text-xs text-ink-muted">Submitted {formatIst(c.created_at)}</p>
        </div>
        <div className="flex items-center gap-2">
          <RequesterStatusBadge status={c.status} awaitingRole={c.awaiting_role} />
          {can('cancel') && (
            <Button size="sm" variant="danger" onClick={() => setCancelling(true)}>
              <XCircle /> Cancel request
            </Button>
          )}
        </div>
      </div>

      <Card>
        <CardBody>
          {c.status === 'DUPLICATE' && c.duplicate_of ? (
            <p>
              The same issue is already being handled under{' '}
              <Link className="font-bold underline" to={`/requests/${c.duplicate_of.id}`}>
                {c.duplicate_of.ref}
              </Link>
              . Follow that request for updates.
            </p>
          ) : c.status === 'CANCELLED' ? (
            <p>This request was cancelled. No further action will be taken.</p>
          ) : (
            <Progress c={c} />
          )}
        </CardBody>
      </Card>

      {asked && can('provide_info') && (
        <RequesterReply
          c={c}
          actions={actions}
          hint={missing.length ? `They asked for: ${missing.join(', ')}.` : undefined}
        />
      )}

      <Card>
        <CardHeader title="Conversation with the operations team" icon={<Mail />} />
        <ul className="divide-y divide-line">
          {thread.length === 0 && (
            <li className="px-4 py-6 text-center text-ink-muted">
              No updates yet. We will notify you here.
            </li>
          )}
          {[...thread].reverse().map((m) => {
            const mine = m.type === 'requester_reply'
            return (
              <li
                key={m.id}
                className={cn('px-4 py-3', mine && 'border-l-4 border-l-accent bg-page')}
              >
                <p className="text-[11px] font-bold tracking-widest text-ink-muted uppercase">
                  {mine ? 'You replied' : 'Operations team'}
                </p>
                <p className="font-bold">{m.subject}</p>
                <p className="text-xs text-ink-muted">
                  {m.status === 'sent'
                    ? formatIst(m.sent_at)
                    : 'Posted here because our email could not reach you'}
                </p>
                <p className="mt-2 text-sm whitespace-pre-line">{m.body}</p>
              </li>
            )
          })}
        </ul>
      </Card>

      <Card>
        <CardHeader title="Your request" />
        <CardBody>
          <p className="text-sm whitespace-pre-line">{c.raw_text}</p>
        </CardBody>
      </Card>

      <ReasonDialog
        open={cancelling}
        onOpenChange={setCancelling}
        title={`Cancel ${c.ref}?`}
        confirmLabel="Cancel request"
        destructive
        pending={actions.cancel.isPending}
        onConfirm={(r) => actions.cancel.mutate(r, { onSuccess: () => setCancelling(false) })}
      />
    </div>
  )
}
