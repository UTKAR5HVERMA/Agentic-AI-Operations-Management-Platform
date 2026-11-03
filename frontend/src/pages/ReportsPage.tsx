import { useMutation } from '@tanstack/react-query'
import { Copy, Download, FileText, Sparkles } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { PriorityBadge, RiskBadge, SourceBadge, StatusBadge } from '@/components/common/badges'
import { KpiTile } from '@/components/common/KpiTile'
import { EmptyState, PageHeader, QueryState } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Table, Td, Th, Tr } from '@/components/ui/table'
import { useDashboard } from '@/hooks/queries'
import { errorMessage, post } from '@/lib/api'
import { formatIst, formatPct } from '@/lib/format'
import type { ManagementSummary } from '@/lib/types'

function download(markdown: string) {
  const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown' }))
  const link = Object.assign(document.createElement('a'), {
    href: url,
    download: `ops-summary-${new Date().toISOString().slice(0, 10)}.md`,
  })
  link.click()
  URL.revokeObjectURL(url)
}

export default function ReportsPage() {
  const dashboard = useDashboard()
  const summary = useMutation({
    mutationFn: () => post<ManagementSummary>('/reports/management-summary'),
    onError: (e) => toast.error(errorMessage(e)),
  })
  const s = summary.data

  return (
    <>
      <PageHeader
        title="Reports"
        subtitle="Management view of operations, approvals and AI quality"
        actions={
          <Button variant="primary" loading={summary.isPending} onClick={() => summary.mutate()}>
            <Sparkles /> Generate management summary
          </Button>
        }
      />
      <QueryState query={dashboard}>
        {(d) => (
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
              <KpiTile label="Open cases" value={d.open_cases} />
              <KpiTile label="Pending approvals" value={d.pending_approvals} />
              <KpiTile label="Overdue" value={d.overdue} alert={d.overdue > 0} />
              <KpiTile label="AI override rate" value={formatPct(d.ai_override_rate)} />
              <KpiTile label="Extraction accuracy" value={formatPct(d.auto_extraction_accuracy)} />
              <KpiTile
                label="Avg agent latency"
                value={`${Math.round(d.avg_agent_latency_ms)} ms`}
                hint={`Fallback rate ${formatPct(d.fallback_rate)}`}
              />
            </div>
            {s && (
              <Card>
                <CardHeader
                  title="Management summary"
                  icon={<FileText />}
                  subtitle={`Generated ${formatIst(s.generated_at)}`}
                  actions={
                    <>
                      <SourceBadge source={s.model === 'template' ? 'system' : 'agent'} />
                      <Button
                        size="sm"
                        onClick={() =>
                          navigator.clipboard
                            .writeText(s.markdown)
                            .then(() => toast.success('Copied'))
                        }
                      >
                        <Copy /> Copy
                      </Button>
                      <Button size="sm" onClick={() => download(s.markdown)}>
                        <Download /> Download .md
                      </Button>
                    </>
                  }
                />
                <CardBody>
                  <article className="space-y-2 text-sm leading-relaxed [&_h2]:mt-4 [&_h2]:border-l-4 [&_h2]:border-accent [&_h2]:pl-2 [&_h2]:text-base [&_ul]:list-disc [&_ul]:pl-5">
                    <ReactMarkdown>{s.markdown}</ReactMarkdown>
                  </article>
                  <p className="mt-4 border-t border-line pt-3 text-xs text-ink-muted">
                    Numbers are computed from the database; AI writes only the narrative.
                  </p>
                </CardBody>
              </Card>
            )}
            <Card>
              <CardHeader title="Critical and escalated cases" />
              {d.critical_cases.length === 0 ? (
                <EmptyState title="No critical cases" />
              ) : (
                <Table>
                  <thead>
                    <tr>
                      <Th>Ref</Th>
                      <Th>Subject</Th>
                      <Th>Priority</Th>
                      <Th>Risk</Th>
                      <Th>Status</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.critical_cases.map((c) => (
                      <Tr key={c.id}>
                        <Td>
                          <Link className="font-bold hover:underline" to={`/requests/${c.id}`}>
                            {c.ref}
                          </Link>
                        </Td>
                        <Td>{c.subject}</Td>
                        <Td>
                          <PriorityBadge priority={c.priority} />
                        </Td>
                        <Td>
                          <RiskBadge level={c.risk_level} />
                        </Td>
                        <Td>
                          <StatusBadge status={c.status} />
                        </Td>
                      </Tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card>
          </div>
        )}
      </QueryState>
    </>
  )
}
