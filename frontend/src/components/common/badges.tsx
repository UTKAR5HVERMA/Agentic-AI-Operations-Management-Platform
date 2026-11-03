import { Bot, Cog, Loader2, UserRound, Zap } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import type { BadgeTone } from '@/components/ui/badge'
import { requesterStatus, ROLE_LABEL, STATUS_LABEL } from '@/lib/labels'
import type { FieldSource, Priority, RiskLevel, Role, Status } from '@/lib/types'
import { cn } from '@/lib/utils'

const STATUS_TONE: Record<Status, BadgeTone> = {
  NEW: 'neutral',
  ANALYZING: 'info',
  NEEDS_INFO: 'warn',
  PENDING_REVIEW: 'violet',
  PENDING_APPROVAL: 'dark',
  APPROVED: 'teal',
  IN_PROGRESS: 'teal',
  ESCALATED: 'warn',
  REJECTED: 'bad',
  ON_HOLD: 'neutral',
  RESOLVED: 'ok',
  CLOSED: 'ok',
  CANCELLED: 'neutral',
  DUPLICATE: 'neutral',
}

export function StatusBadge({ status }: { status: Status }) {
  const struck = status === 'CANCELLED' || status === 'DUPLICATE'
  return (
    <Badge tone={STATUS_TONE[status]} className={cn(struck && 'line-through')}>
      {status === 'ANALYZING' && <Loader2 className="animate-spin" />}
      {STATUS_LABEL[status]}
    </Badge>
  )
}

const PRIORITY_TONE: Record<Priority, BadgeTone> = {
  P1: 'bad',
  P2: 'warn',
  P3: 'accent',
  P4: 'neutral',
}

export function PriorityBadge({ priority }: { priority: Priority }) {
  return <Badge tone={PRIORITY_TONE[priority]}>{priority}</Badge>
}

const RISK_TONE: Record<RiskLevel, BadgeTone> = {
  low: 'ok',
  medium: 'accent',
  high: 'warn',
  critical: 'bad',
}

export function RiskBadge({ level }: { level: RiskLevel | null }) {
  if (!level) return <span className="text-ink-muted">—</span>
  return <Badge tone={RISK_TONE[level]}>{level}</Badge>
}

/** AI output is always labelled (FRONTEND.md §8 rule 1). */
export function SourceBadge({ source }: { source: FieldSource | 'agent' | 'system' }) {
  if (source === 'human')
    return (
      <Badge tone="dark">
        <UserRound /> Human
      </Badge>
    )
  if (source === 'fallback')
    return (
      <Badge tone="warn">
        <Cog /> Fallback
      </Badge>
    )
  if (source === 'event' || source === 'system')
    return (
      <Badge tone="info">
        <Zap /> {source === 'event' ? 'Event' : 'System'}
      </Badge>
    )
  return (
    <Badge tone="violet">
      <Bot /> AI
    </Badge>
  )
}

export function RoleBadge({ role }: { role: Role }) {
  return <Badge tone="accent">{ROLE_LABEL[role]}</Badge>
}

export function RequesterStatusBadge({
  status,
  awaitingRole,
}: {
  status: Status
  awaitingRole: Role | null
}) {
  return <Badge tone={STATUS_TONE[status]}>{requesterStatus(status, awaitingRole)}</Badge>
}
