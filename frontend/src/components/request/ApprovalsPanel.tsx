import { CheckSquare, RotateCcw } from 'lucide-react'
import { SlaTimer } from '@/components/common/SlaTimer'
import { Badge } from '@/components/ui/badge'
import type { BadgeTone } from '@/components/ui/badge'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { formatInr, formatIst } from '@/lib/format'
import { ROLE_LABEL } from '@/lib/labels'
import type { Approval, ApprovalStatus, RequestDetail } from '@/lib/types'
import { ApprovalAdviceCard } from './ApprovalAdviceCard'
import { ApprovalDecision } from './ApprovalDecision'

const TONE: Record<ApprovalStatus, BadgeTone> = {
  pending: 'dark',
  escalated: 'warn',
  approved: 'ok',
  rejected: 'bad',
  expired: 'neutral',
  cancelled: 'neutral',
}

const KIND_LABEL: Record<Approval['kind'], string> = {
  financial: 'spend authority',
  operational: 'operational sign-off',
  endorsement: 'manager review → Director',
}

function ApprovalRow({ a }: { a: Approval }) {
  const open = a.status === 'pending' || a.status === 'escalated'
  return (
    <div className="border-b border-line px-4 py-3 last:border-0">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={TONE[a.status]}>{a.status}</Badge>
        <span className="font-bold">
          {a.assigned_to ? a.assigned_to.name : ROLE_LABEL[a.approver_role]}
        </span>
        {a.assigned_to && (
          <span className="text-xs text-ink-muted">({ROLE_LABEL[a.approver_role]})</span>
        )}
        <span className="text-xs text-ink-muted">({KIND_LABEL[a.kind]})</span>
        {a.escalation_level > 0 && <Badge tone="warn">Escalation L{a.escalation_level}</Badge>}
        {a.self_approved && <Badge tone="bad">Self-approved by Director · review</Badge>}
        {a.stale && open && (
          <Badge tone="info">
            <RotateCcw /> Re-confirm required
          </Badge>
        )}
        <span className="ml-auto font-bold tabular-nums">{formatInr(a.amount_inr)}</span>
      </div>
      <p className="mt-1 text-sm">{a.recommendation_title}</p>
      <div className="mt-1 flex flex-wrap gap-x-4 text-xs text-ink-muted">
        {open ? (
          <span>
            Due <SlaTimer target={a.due_at} />
          </span>
        ) : (
          <span>
            Decided {formatIst(a.decided_at)}
            {a.approver && ` by ${a.approver.name}`}
          </span>
        )}
        {a.reasons.length > 0 && <span>Why: {a.reasons.join('; ')}</span>}
      </div>
      {a.stale && a.stale_reason && open && (
        <p className="mt-1 text-xs text-info">Changed since request: {a.stale_reason}</p>
      )}
      {a.routing_note && (
        <p className="mt-1 text-sm">
          <span className="text-xs font-bold text-ink-muted">Operations Team: </span>“
          {a.routing_note}”
        </p>
      )}
      {a.decision_note && <p className="mt-1 text-sm">“{a.decision_note}”</p>}
      {open && a.advice && <ApprovalAdviceCard advice={a.advice} />}
      <div className="mt-2">
        <ApprovalDecision a={a} />
      </div>
    </div>
  )
}

export function ApprovalsPanel({ c }: { c: RequestDetail }) {
  if (c.approvals.length === 0) return null
  return (
    <Card>
      <CardHeader
        title="Approvals"
        icon={<CheckSquare />}
        subtitle="Deterministic policy: amount, risk, confidence, injection. Never auto-approved."
      />
      <CardBody className="p-0">
        {[...c.approvals].reverse().map((a) => (
          <ApprovalRow key={a.id} a={a} />
        ))}
      </CardBody>
    </Card>
  )
}
