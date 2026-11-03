import { AlertTriangle, Copy, ShieldAlert, Zap } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { PriorityBadge, RequesterStatusBadge, StatusBadge } from '@/components/common/badges'
import { SlaTimer } from '@/components/common/SlaTimer'
import { EmptyState } from '@/components/common/states'
import { Table, Td, Th, Tr } from '@/components/ui/table'
import { Tooltip } from '@/components/ui/tooltip'
import { formatIst, timeAgo } from '@/lib/format'
import { CATEGORY_LABEL } from '@/lib/labels'
import type { RequestSummary } from '@/lib/types'

const DONE = new Set(['CLOSED', 'CANCELLED', 'DUPLICATE', 'RESOLVED'])

function Flags({ r }: { r: RequestSummary }) {
  const flags = [
    r.open_issues > 0 && {
      icon: AlertTriangle,
      tone: 'text-warn',
      tip: `${r.open_issues} open issue(s)`,
    },
    r.status === 'DUPLICATE' && { icon: Copy, tone: 'text-ink-muted', tip: 'Duplicate' },
    r.injection_flag && {
      icon: ShieldAlert,
      tone: 'text-bad',
      tip: 'Suspicious content quarantined',
    },
    r.degraded && { icon: Zap, tone: 'text-warn', tip: 'Degraded: ran on fallback' },
  ].filter(Boolean) as { icon: typeof Zap; tone: string; tip: string }[]
  return (
    <span className="flex gap-1.5">
      {flags.map(({ icon: Icon, tone, tip }) => (
        <Tooltip key={tip} content={tip}>
          <Icon className={`size-4 ${tone}`} aria-label={tip} />
        </Tooltip>
      ))}
    </span>
  )
}

/** `simple` = requester view: only what the requester needs to track their request. */
export function RequestsTable({
  rows,
  simple = false,
}: {
  rows: RequestSummary[]
  simple?: boolean
}) {
  const navigate = useNavigate()
  if (rows.length === 0)
    return (
      <EmptyState
        title="No requests found"
        hint={
          simple
            ? 'Requests you submit will appear here.'
            : 'Try clearing filters, or create a new request.'
        }
      />
    )
  const open = (id: string) => navigate(`/requests/${id}`)
  return (
    <Table>
      <thead>
        <tr>
          <Th>Ref</Th>
          <Th>Subject</Th>
          {simple ? (
            <>
              <Th>Status</Th>
              <Th>Submitted</Th>
            </>
          ) : (
            <>
              <Th>Category</Th>
              <Th>Priority</Th>
              <Th>Status</Th>
              <Th>Deadline</Th>
              <Th>Flags</Th>
              <Th>Sender</Th>
            </>
          )}
          <Th>Updated</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <Tr
            key={r.id}
            className="cursor-pointer"
            tabIndex={0}
            onClick={() => open(r.id)}
            onKeyDown={(e) => e.key === 'Enter' && open(r.id)}
          >
            <Td className="font-bold whitespace-nowrap">{r.ref}</Td>
            <Td className="max-w-80 truncate" title={r.subject}>
              {r.subject}
            </Td>
            {simple ? (
              <>
                <Td>
                  <RequesterStatusBadge status={r.status} awaitingRole={r.awaiting_role} />
                </Td>
                <Td className="whitespace-nowrap text-ink-muted">{formatIst(r.created_at)}</Td>
              </>
            ) : (
              <>
                <Td className="whitespace-nowrap text-ink-muted">{CATEGORY_LABEL[r.category]}</Td>
                <Td>
                  <PriorityBadge priority={r.priority} />
                </Td>
                <Td>
                  <StatusBadge status={r.status} />
                </Td>
                <Td>
                  <SlaTimer target={r.deadline_at} done={DONE.has(r.status)} />
                </Td>
                <Td>
                  <Flags r={r} />
                </Td>
                <Td className="max-w-40 truncate text-ink-muted">
                  {r.sender.name ?? r.sender.email ?? '—'}
                </Td>
              </>
            )}
            <Td className="whitespace-nowrap text-ink-muted">{timeAgo(r.updated_at)}</Td>
          </Tr>
        ))}
      </tbody>
    </Table>
  )
}
