import { Ban, Copy, Info, MailWarning, ShieldAlert, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import type { CaseActions } from '@/hooks/useCaseActions'
import { formatIst } from '@/lib/format'
import type { RequestDetail } from '@/lib/types'
import { cn } from '@/lib/utils'
import { ClarifyButton } from './ClarifyButton'

const TONES = {
  red: 'border-bad bg-bad/5',
  amber: 'border-warn bg-warn/10',
  blue: 'border-info bg-info/5',
  grey: 'border-ink-muted bg-white',
}

function Banner({
  tone,
  icon,
  title,
  children,
  actions,
}: {
  tone: keyof typeof TONES
  icon: ReactNode
  title: ReactNode
  children?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div
      className={cn('flex gap-3 border-l-4 px-4 py-3 ring-1 ring-line', TONES[tone])}
      role="status"
    >
      <span className="mt-0.5 [&_svg]:size-4">{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="font-bold">{title}</p>
        {children && <div className="mt-1 text-sm text-ink/80">{children}</div>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-start gap-2">{actions}</div>}
    </div>
  )
}

export function CaseBanners({ c, actions }: { c: RequestDetail; actions: CaseActions }) {
  const [showSpans, setShowSpans] = useState(false)
  const can = (a: string) => c.allowed_actions.includes(a)
  const open = (type: string) => c.issues.filter((i) => i.type === type && i.status === 'open')
  const dup = c.duplicates[0]
  const changed = open('circumstances_changed')
  const undelivered = open('communication_failure')
  const low = open('low_confidence').find((i) => !i.field)
  const spans = c.injection.quarantined_spans ?? []
  const cancelled =
    c.status === 'CANCELLED' ? c.events.find((e) => e.type === 'launch_postponed') : undefined

  return (
    <div className="mb-5 space-y-2 empty:hidden">
      {c.duplicate_of && (
        <Banner
          tone="grey"
          icon={<Copy />}
          title={
            <>
              Linked as a duplicate of{' '}
              <Link className="underline" to={`/requests/${c.duplicate_of.id}`}>
                {c.duplicate_of.ref}
              </Link>
            </>
          }
          actions={
            can('not_duplicate') && (
              <Button
                size="sm"
                onClick={() => actions.notDuplicate.mutate(undefined)}
                loading={actions.notDuplicate.isPending}
              >
                Not a duplicate
              </Button>
            )
          }
        >
          The original case is the single source of truth; the sender was notified.
        </Banner>
      )}
      {!c.duplicate_of && dup && c.status !== 'DUPLICATE' && can('mark_duplicate') && (
        <Banner
          tone="amber"
          icon={<Copy />}
          title={`Likely duplicate of ${dup.ref} (${Math.round(dup.similarity * 100)}% match)`}
          actions={
            <>
              <Button size="sm" asChild>
                <Link to={`/requests/${dup.id}`}>View</Link>
              </Button>
              <Button
                size="sm"
                variant="dark"
                onClick={() => actions.markDuplicate.mutate(dup.id)}
                loading={actions.markDuplicate.isPending}
              >
                Merge into it
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => actions.notDuplicate.mutate(undefined)}
              >
                Not a duplicate
              </Button>
            </>
          }
        />
      )}
      {c.injection.flag && (
        <Banner
          tone="red"
          icon={<ShieldAlert className="text-bad" />}
          title="Suspicious instructions detected and quarantined. They were NOT followed."
          actions={
            <Button size="sm" variant="ghost" onClick={() => setShowSpans((s) => !s)}>
              {showSpans ? 'Hide' : 'Show'} spans
            </Button>
          }
        >
          Patterns: {(c.injection.patterns ?? []).join(', ')}. AI can never approve or send
          anything, regardless of email content.
          {showSpans && (
            <ul className="mt-2 space-y-1">
              {spans.map((s) => (
                <li
                  key={s.start}
                  className="bg-bad/10 px-2 py-1 font-mono text-xs text-bad line-through"
                >
                  {s.text}
                </li>
              ))}
            </ul>
          )}
        </Banner>
      )}
      {undelivered.map((i) => (
        <Banner
          key={i.id}
          tone="red"
          icon={<MailWarning className="text-bad" />}
          title="A message was not delivered"
        >
          {i.message} Open it under Messages to retry now.
        </Banner>
      ))}
      {changed.map((i) => (
        <Banner
          key={i.id}
          tone={i.severity === 'blocker' ? 'amber' : 'blue'}
          icon={<Info className="text-info" />}
          title="Circumstances changed"
        >
          {i.message} <span className="text-ink-muted">({formatIst(i.created_at)})</span>
        </Banner>
      ))}
      {c.status === 'CANCELLED' && (
        <Banner tone="grey" icon={<Ban />} title="This request was cancelled">
          {cancelled ? 'Triggered by a launch postponement. ' : ''}Pending approvals were cancelled,
          reserved stock released and notices drafted — see Communications and Timeline.
        </Banner>
      )}
      {low && (
        <Banner
          tone="amber"
          icon={<TriangleAlert className="text-warn" />}
          title="Not enough evidence to recommend an action safely"
          actions={<ClarifyButton c={c} actions={actions} />}
        >
          {low.message.replace('Not enough evidence to recommend an action safely. ', '')}
        </Banner>
      )}
    </div>
  )
}
