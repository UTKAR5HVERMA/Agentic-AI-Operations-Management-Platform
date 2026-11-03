import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  Info,
  ListChecks,
  RefreshCw,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { ReasonDialog } from '@/components/common/ReasonDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { useHealth } from '@/hooks/queries'
import type { CaseActions } from '@/hooks/useCaseActions'
import { useCaseNav } from '@/hooks/useCaseNav'
import { clarifyQuestions, openIssues } from '@/lib/caseFlow'
import { titleCase } from '@/lib/format'
import type { Issue, RequestDetail, Severity } from '@/lib/types'
import { cn } from '@/lib/utils'
import { ClarifyButton } from './ClarifyButton'
import { ConflictCard } from './ConflictCard'

const SEVERITY: Record<Severity, { icon: typeof Info; tone: string; order: number }> = {
  blocker: { icon: AlertOctagon, tone: 'border-bad', order: 0 },
  warning: { icon: AlertTriangle, tone: 'border-warn', order: 1 },
  info: { icon: Info, tone: 'border-info', order: 2 },
}

function IssueActions({
  issue,
  c,
  actions,
  onDismiss,
  onHandle,
  onShowRisk,
}: {
  issue: Issue
  c: RequestDetail
  actions: CaseActions
  onDismiss: () => void
  onHandle: () => void
  onShowRisk?: () => void
}) {
  const health = useHealth()
  const nav = useCaseNav()
  const can = (a: string) => c.allowed_actions.includes(a)
  const multiIssue = issue.type === 'ambiguity' && c.sub_requests.length >= 2
  const systemsDown =
    health.data && (health.data.llm === 'down' || health.data.inventory === 'down')
  return (
    <div className="flex flex-wrap gap-2">
      {multiIssue && can('resolve_issue') && (
        <Button size="sm" variant="dark" onClick={onHandle}>
          <ListChecks /> Handle in this request
        </Button>
      )}
      {issue.type === 'system_unavailable' && can('reanalyze') && (
        <Button
          size="sm"
          disabled={Boolean(systemsDown)}
          title={systemsDown ? 'Waiting for systems to recover' : undefined}
          onClick={() => actions.reanalyze.mutate(undefined)}
        >
          <RefreshCw /> Re-analyze
        </Button>
      )}
      {issue.type === 'extraction_flagged' && nav && (
        <Button size="sm" variant="primary" onClick={() => nav.goTo('extraction')}>
          Correct the value
        </Button>
      )}
      {issue.type === 'agent_disagreement' && onShowRisk && (
        <Button size="sm" variant="link" onClick={onShowRisk}>
          See both assessments
        </Button>
      )}
      {can('resolve_issue') && (
        <Button size="sm" variant="ghost" onClick={onDismiss}>
          <X /> Dismiss
        </Button>
      )}
    </div>
  )
}

export function IssuesPanel({
  c,
  actions,
  onShowRisk,
}: {
  c: RequestDetail
  actions: CaseActions
  onShowRisk?: () => void
}) {
  // One reason dialog: "dismiss" drops an issue, "resolved" confirms handling it in this case.
  const [closing, setClosing] = useState<{ issue: Issue; resolution: 'dismiss' | 'resolved' }>()
  const open = openIssues(c).sort((a, b) => SEVERITY[a.severity].order - SEVERITY[b.severity].order)
  const closed = c.issues.filter((i) => i.status !== 'open').length

  return (
    <Card>
      <CardHeader
        title="Issues"
        icon={<AlertTriangle />}
        subtitle={`${open.length} open · ${closed} resolved or dismissed`}
        actions={
          // One combined clarification for every question (incl. "which issue first?").
          (clarifyQuestions(c).length > 0 || c.sub_requests.length >= 2) && (
            <ClarifyButton c={c} actions={actions} />
          )
        }
      />
      <CardBody className="space-y-3">
        {open.length === 0 && (
          <p className="flex items-center gap-2 text-ok">
            <CheckCircle2 className="size-4" /> No open issues.
          </p>
        )}
        {open.map((issue) => {
          if (issue.type === 'conflict')
            return (
              <ConflictCard
                key={issue.id}
                issue={issue}
                actions={actions}
                canResolve={c.allowed_actions.includes('resolve_issue')}
              />
            )
          const { icon: Icon, tone } = SEVERITY[issue.severity]
          const subs = issue.type === 'ambiguity' ? c.sub_requests : []
          return (
            <div
              key={issue.id}
              className={cn('border-l-4 bg-white px-4 py-3 ring-1 ring-line', tone)}
            >
              <div className="flex items-start gap-2">
                <Icon className="mt-0.5 size-4 shrink-0" />
                <div className="min-w-0 flex-1 space-y-2">
                  <p>
                    <Badge
                      tone={
                        issue.severity === 'blocker'
                          ? 'bad'
                          : issue.severity === 'warning'
                            ? 'warn'
                            : 'info'
                      }
                      className="mr-2"
                    >
                      {titleCase(issue.type)}
                    </Badge>
                    {issue.message}
                  </p>
                  {subs.length > 0 && (
                    <ol className="list-decimal space-y-1 pl-5 text-sm">
                      {subs.map((s) => (
                        <li key={s.title}>
                          {s.title}{' '}
                          <span className="text-xs text-ink-muted">({titleCase(s.category)})</span>
                        </li>
                      ))}
                    </ol>
                  )}
                  <IssueActions
                    issue={issue}
                    c={c}
                    actions={actions}
                    onDismiss={() => setClosing({ issue, resolution: 'dismiss' })}
                    onHandle={() => setClosing({ issue, resolution: 'resolved' })}
                    onShowRisk={onShowRisk}
                  />
                </div>
              </div>
            </div>
          )
        })}
      </CardBody>
      <ReasonDialog
        open={closing !== undefined}
        onOpenChange={(o) => !o && setClosing(undefined)}
        title={closing?.resolution === 'resolved' ? 'Handle in this request' : 'Dismiss issue'}
        description={
          closing?.resolution === 'resolved'
            ? 'All issues stay in this request and the analysis continues. Note how you will handle them.'
            : closing?.issue.message
        }
        confirmLabel={closing?.resolution === 'resolved' ? 'Continue' : 'Dismiss'}
        pending={actions.resolveIssue.isPending}
        onConfirm={(note) =>
          closing &&
          actions.resolveIssue.mutate(
            { issueId: closing.issue.id, resolution: closing.resolution, note },
            { onSuccess: () => setClosing(undefined) },
          )
        }
      />
    </Card>
  )
}
