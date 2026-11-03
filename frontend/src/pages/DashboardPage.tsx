import { ArrowRight, PlusSquare } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Link, Navigate } from 'react-router-dom'
import { PriorityBadge, RiskBadge, StatusBadge } from '@/components/common/badges'
import { KpiTile } from '@/components/common/KpiTile'
import { EmptyState, PageHeader, QueryState } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { useApprovals, useDashboard } from '@/hooks/queries'
import { useAuth } from '@/lib/auth'
import { formatInr, formatPct } from '@/lib/format'
import { CATEGORY_LABEL, STATUS_LABEL } from '@/lib/labels'
import { APPROVER_ROLES } from '@/lib/roles'
import type { Category, Dashboard, Status } from '@/lib/types'

const CHART_COLORS = ['#2E2E38', '#FFE600', '#747480', '#188CE5', '#27ACAA', '#FF9831', '#724BC3']

function MetricsRow({ d }: { d: Dashboard }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
      <KpiTile label="Open cases" value={d.open_cases} hint={`${d.total_cases} total`} />
      <KpiTile label="P1 open" value={d.by_priority.P1 ?? 0} alert={(d.by_priority.P1 ?? 0) > 0} />
      <KpiTile label="Pending approvals" value={d.pending_approvals} />
      <KpiTile
        label="Overdue (SLA)"
        value={d.overdue}
        alert={d.overdue > 0}
        hint={`${d.approval_sla_breaches} approval escalations`}
      />
      <KpiTile label="Avg time to close" value={`${d.avg_time_to_close_hours}h`} />
      <KpiTile
        label="AI override rate"
        value={formatPct(d.ai_override_rate)}
        hint={`Extraction accuracy ${formatPct(d.auto_extraction_accuracy)}`}
      />
      <KpiTile
        label="Degraded cases"
        value={d.degraded_cases}
        alert={d.degraded_cases > 0}
        hint={`Fallback rate ${formatPct(d.fallback_rate)}`}
      />
    </div>
  )
}

function ChartCard({ title, data }: { title: string; data: { name: string; value: number }[] }) {
  return (
    <Card>
      <CardHeader title={title} />
      <CardBody className="h-64">
        {data.length === 0 ? (
          <EmptyState title="No data yet" />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} layout="vertical" margin={{ left: 20, right: 16 }}>
              <CartesianGrid horizontal={false} stroke="#E1E1E6" />
              <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11, fill: '#747480' }} />
              <YAxis
                type="category"
                dataKey="name"
                width={120}
                tick={{ fontSize: 11, fill: '#2E2E38' }}
              />
              <Tooltip cursor={{ fill: '#F6F6FA' }} />
              <Bar dataKey="value" barSize={14}>
                {data.map((_, i) => (
                  <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardBody>
    </Card>
  )
}

function Attention({ d }: { d: Dashboard }) {
  const { hasRole } = useAuth()
  const approvals = useApprovals('pending', true, hasRole(...APPROVER_ROLES))
  const mine = (approvals.data ?? []).filter((a) => a.can_decide)
  return (
    <Card>
      <CardHeader
        title="Needs your attention"
        subtitle="Approvals assigned to you, critical and escalated cases"
      />
      <ul className="divide-y divide-line">
        {mine.map((a) => (
          <li key={a.id}>
            <Link
              to={`/requests/${a.request_id}`}
              className="flex items-center gap-3 px-4 py-3 hover:bg-page"
            >
              <span className="shrink-0 font-bold whitespace-nowrap">{a.request_ref}</span>
              <span className="min-w-0 flex-1 truncate">Approve: {a.recommendation_title}</span>
              <span className="font-bold tabular-nums">{formatInr(a.amount_inr)}</span>
              <ArrowRight className="size-4 text-ink-muted" />
            </Link>
          </li>
        ))}
        {d.critical_cases.map((c) => (
          <li key={c.id}>
            <Link to={`/requests/${c.id}`} className="block px-4 py-3 hover:bg-page">
              <span className="flex flex-wrap items-center gap-1.5">
                <span className="mr-1 font-bold whitespace-nowrap">{c.ref}</span>
                <PriorityBadge priority={c.priority} />
                <RiskBadge level={c.risk_level} />
                <StatusBadge status={c.status} />
              </span>
              <span className="mt-1 block truncate text-xs text-ink-muted">{c.subject}</span>
            </Link>
          </li>
        ))}
        {mine.length === 0 && d.critical_cases.length === 0 && (
          <li>
            <EmptyState title="All clear" hint="Nothing critical or waiting on you right now." />
          </li>
        )}
      </ul>
    </Card>
  )
}

export default function DashboardPage() {
  const { user } = useAuth()
  const isRequester = user?.role === 'requester'
  const dashboard = useDashboard(!isRequester)
  if (isRequester) return <Navigate to="/requests" replace /> // requesters work from their list
  const newButton = (
    <Button asChild variant="primary">
      <Link to="/requests/new">
        <PlusSquare /> New request
      </Link>
    </Button>
  )
  return (
    <>
      <PageHeader
        title="Operations dashboard"
        subtitle={`Welcome back, ${user?.name}`}
        actions={newButton}
      />
      <QueryState query={dashboard}>
        {(d) => (
          <div className="space-y-5">
            <MetricsRow d={d} />
            <div className="grid gap-5 xl:grid-cols-3">
              <ChartCard
                title="Cases by status"
                data={Object.entries(d.counts_by_status).map(([k, v]) => ({
                  name: STATUS_LABEL[k as Status],
                  value: v ?? 0,
                }))}
              />
              <ChartCard
                title="Cases by category"
                data={Object.entries(d.by_category).map(([k, v]) => ({
                  name: CATEGORY_LABEL[k as Category],
                  value: v ?? 0,
                }))}
              />
              <Attention d={d} />
            </div>
          </div>
        )}
      </QueryState>
    </>
  )
}
