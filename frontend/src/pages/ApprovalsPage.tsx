import { useState } from 'react'
import { Link } from 'react-router-dom'
import { RiskBadge } from '@/components/common/badges'
import { SlaTimer } from '@/components/common/SlaTimer'
import { EmptyState, PageHeader, QueryState } from '@/components/common/states'
import { ApprovalDecision } from '@/components/request/ApprovalDecision'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Table, Td, Th, Tr } from '@/components/ui/table'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useApprovals } from '@/hooks/queries'
import { formatInr, formatIst } from '@/lib/format'
import { ROLE_LABEL } from '@/lib/labels'
import type { Approval } from '@/lib/types'

function InboxTable({ rows, decided }: { rows: Approval[]; decided: boolean }) {
  if (rows.length === 0)
    return (
      <EmptyState
        title="Nothing here"
        hint={decided ? 'No decisions yet.' : 'You are all caught up.'}
      />
    )
  return (
    <Table>
      <thead>
        <tr>
          <Th>Case</Th>
          <Th>Recommendation</Th>
          <Th>Amount</Th>
          <Th>Risk</Th>
          <Th>Assigned to</Th>
          <Th>Requested by</Th>
          <Th>{decided ? 'Decision' : 'Due'}</Th>
          <Th>{decided ? 'Note' : 'Action'}</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((a) => (
          <Tr key={a.id}>
            <Td className="whitespace-nowrap">
              <Link
                className="font-bold underline-offset-2 hover:underline"
                to={`/requests/${a.request_id}`}
              >
                {a.request_ref}
              </Link>
              {a.escalation_level > 0 && (
                <Badge tone="warn" className="ml-2">
                  L{a.escalation_level}
                </Badge>
              )}
              {a.stale && !decided && (
                <Badge tone="info" className="ml-2">
                  Re-confirm
                </Badge>
              )}
            </Td>
            <Td className="max-w-72">
              <p className="font-bold">{a.recommendation_title}</p>
              <p className="truncate text-xs text-ink-muted">{a.request_subject}</p>
            </Td>
            <Td className="font-bold whitespace-nowrap tabular-nums">{formatInr(a.amount_inr)}</Td>
            <Td>
              <RiskBadge level={a.risk_level} />
            </Td>
            <Td className="whitespace-nowrap">
              {a.assigned_to?.name ?? ROLE_LABEL[a.approver_role]}
            </Td>
            <Td className="max-w-40 truncate text-ink-muted">{a.requested_by ?? '—'}</Td>
            <Td className="whitespace-nowrap">
              {decided ? (
                <>
                  <Badge tone={a.status === 'approved' ? 'ok' : 'bad'}>{a.status}</Badge>
                  <p className="text-xs text-ink-muted">{formatIst(a.decided_at)}</p>
                </>
              ) : (
                <SlaTimer target={a.due_at} />
              )}
            </Td>
            <Td>
              {decided ? (
                <span className="text-xs">{a.decision_note ?? '—'}</span>
              ) : (
                <ApprovalDecision a={a} />
              )}
            </Td>
          </Tr>
        ))}
      </tbody>
    </Table>
  )
}

export default function ApprovalsPage() {
  const [tab, setTab] = useState<'pending' | 'decided' | 'escalated'>('pending')
  const approvals = useApprovals(tab, true)
  return (
    <>
      <PageHeader
        title="Approvals"
        subtitle="Your approval inbox. Only the assigned manager can decide; limits and segregation of duties are enforced by the server."
      />
      <Tabs value={tab} onValueChange={(v) => setTab(v as typeof tab)}>
        <TabsList className="mb-4">
          <TabsTrigger value="pending">Pending</TabsTrigger>
          <TabsTrigger value="escalated">Escalated</TabsTrigger>
          <TabsTrigger value="decided">Decided</TabsTrigger>
        </TabsList>
      </Tabs>
      <Card>
        <QueryState query={approvals}>
          {(rows) => <InboxTable rows={rows} decided={tab === 'decided'} />}
        </QueryState>
      </Card>
    </>
  )
}
