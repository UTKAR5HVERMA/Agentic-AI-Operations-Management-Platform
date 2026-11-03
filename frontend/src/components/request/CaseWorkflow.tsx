import { ArrowLeft, ArrowRight } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardBody } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { CaseActions } from '@/hooks/useCaseActions'
import { useAuth } from '@/lib/auth'
import { STEPS, nextStep, stepStatus } from '@/lib/caseFlow'
import type { StepId } from '@/lib/caseFlow'
import type { RequestDetail } from '@/lib/types'
import { AgentTracePanel } from './AgentTracePanel'
import { ApprovalsPanel } from './ApprovalsPanel'
import { CaseStepBar, NextStepBar } from './CaseStepBar'
import { CommunicationsPanel } from './CommunicationsPanel'
import { EventsPanel } from './EventsPanel'
import { ExtractedFields } from './ExtractedFields'
import { IssuesPanel } from './IssuesPanel'
import { RecommendationsPanel } from './RecommendationsPanel'
import { RiskPanel } from './RiskPanel'
import { SourcePanel } from './SourcePanel'
import { Timeline } from './Timeline'

function HistoryStep({ c }: { c: RequestDetail }) {
  const { user } = useAuth()
  return (
    <Card>
      <CardBody>
        <Tabs defaultValue="timeline">
          <TabsList>
            <TabsTrigger value="timeline">Audit timeline</TabsTrigger>
            <TabsTrigger value="agents">Agent trace</TabsTrigger>
            <TabsTrigger value="events">Events ({c.events.length})</TabsTrigger>
            {user?.role === 'admin' && <TabsTrigger value="json">Raw JSON</TabsTrigger>}
          </TabsList>
          <TabsContent value="timeline">
            <Timeline requestId={c.id} />
          </TabsContent>
          <TabsContent value="agents">
            <AgentTracePanel c={c} />
          </TabsContent>
          <TabsContent value="events">
            <EventsPanel c={c} />
          </TabsContent>
          {user?.role === 'admin' && (
            <TabsContent value="json">
              <pre className="max-h-[480px] overflow-auto bg-ink p-4 font-mono text-xs text-white">
                {JSON.stringify(c, null, 2)}
              </pre>
            </TabsContent>
          )}
        </Tabs>
      </CardBody>
    </Card>
  )
}

/** Staff case view: one workflow step at a time, in assessment order, with a "next step" hint. */
export function CaseWorkflow({
  c,
  actions,
  step,
  onStep,
}: {
  c: RequestDetail
  actions: CaseActions
  step: StepId
  onStep: (step: StepId) => void
}) {
  const next = nextStep(c)
  const [evidence, setEvidence] = useState<string | null>(null)

  const index = STEPS.findIndex((s) => s.id === step)
  const go = (id: StepId) => onStep(id)
  const inFlight = c.approvals.some((a) => a.status === 'pending' || a.status === 'escalated')

  const content: Record<StepId, ReactNode> = {
    request: <SourcePanel c={c} active={evidence} />,
    extraction: (
      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <ExtractedFields c={c} actions={actions} onHighlight={setEvidence} />
        <div className="xl:sticky xl:top-24">
          <SourcePanel c={c} active={evidence} />
        </div>
      </div>
    ),
    issues: <IssuesPanel c={c} actions={actions} onShowRisk={() => go('risk')} />,
    risk: <RiskPanel c={c} />,
    decision: (
      <div className="space-y-5">
        {inFlight && <ApprovalsPanel c={c} />}
        <RecommendationsPanel c={c} actions={actions} />
        {!inFlight && <ApprovalsPanel c={c} />}
        <CommunicationsPanel c={c} actions={actions} />
      </div>
    ),
    history: <HistoryStep c={c} />,
  }

  return (
    <>
      <NextStepBar next={next} active={step} onGo={go} />
      <CaseStepBar active={step} status={stepStatus(c)} onSelect={go} />
      <section aria-label={STEPS[index].label}>{content[step]}</section>
      <div className="mt-5 flex justify-between border-t border-line pt-4">
        {index > 0 ? (
          <Button size="sm" variant="ghost" onClick={() => go(STEPS[index - 1].id)}>
            <ArrowLeft /> {STEPS[index - 1].label}
          </Button>
        ) : (
          <span />
        )}
        {index < STEPS.length - 1 && (
          <Button size="sm" onClick={() => go(STEPS[index + 1].id)}>
            Next: {STEPS[index + 1].label} <ArrowRight />
          </Button>
        )}
      </div>
    </>
  )
}
