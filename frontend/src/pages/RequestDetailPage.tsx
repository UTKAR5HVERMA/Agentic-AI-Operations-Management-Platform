import { Bot } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { QueryState } from '@/components/common/states'
import { AgentStepper } from '@/components/request/AgentStepper'
import { CaseBanners } from '@/components/request/CaseBanners'
import { CaseWorkflow } from '@/components/request/CaseWorkflow'
import { RequestHeader } from '@/components/request/RequestHeader'
import { RequesterCaseView } from '@/components/request/RequesterCaseView'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { useRequest } from '@/hooks/queries'
import { useCaseActions } from '@/hooks/useCaseActions'
import { CaseNavContext } from '@/hooks/useCaseNav'
import type { CaseNav } from '@/hooks/useCaseNav'
import { nextStep } from '@/lib/caseFlow'
import type { StepId } from '@/lib/caseFlow'
import { useAuth } from '@/lib/auth'
import type { RequestDetail } from '@/lib/types'

function CaseView({ c }: { c: RequestDetail }) {
  const actions = useCaseActions(c)
  // The chosen step resets to "where the work is" whenever the case status changes.
  const [chosen, setChosen] = useState<{ status: string; step: StepId } | null>(null)
  const [openCommId, setOpenCommId] = useState<string | null>(null)
  const step = chosen?.status === c.status ? chosen.step : nextStep(c).step
  const nav = useMemo<CaseNav>(() => {
    const goTo = (s: StepId) => {
      setChosen({ status: c.status, step: s })
      document.querySelector('main')?.scrollTo({ top: 0, behavior: 'smooth' })
    }
    return {
      step,
      goTo,
      openCommId,
      openComm: (id) => {
        goTo('decision')
        setOpenCommId(id)
      },
      closeComm: () => setOpenCommId(null),
    }
  }, [c.status, step, openCommId])

  return (
    <CaseNavContext.Provider value={nav}>
      <RequestHeader c={c} actions={actions} />
      <CaseBanners c={c} actions={actions} />
      <CaseWorkflow c={c} actions={actions} step={step} onStep={nav.goTo} />
    </CaseNavContext.Provider>
  )
}

function AnalysingView({ c }: { c: RequestDetail }) {
  return (
    <div className="space-y-5">
      <div>
        <p className="text-xs font-bold tracking-widest text-ink-muted uppercase">{c.ref}</p>
        <h1 className="mt-1 border-l-4 border-accent pl-3 text-2xl">{c.subject}</h1>
      </div>
      <Card>
        <CardHeader
          title="AI analysis in progress"
          icon={<Bot />}
          subtitle="The agents are working on this request; results appear here automatically."
        />
        <CardBody>
          <AgentStepper done={false} />
        </CardBody>
      </Card>
    </div>
  )
}

export default function RequestDetailPage() {
  const { id = '' } = useParams()
  const request = useRequest(id)
  const { user } = useAuth()
  return (
    <QueryState query={request}>
      {(c) =>
        user?.role === 'requester' ? (
          <RequesterCaseView key={c.id} c={c} />
        ) : c.status === 'NEW' || c.status === 'ANALYZING' ? (
          <AnalysingView c={c} />
        ) : (
          <CaseView key={c.id} c={c} />
        )
      }
    </QueryState>
  )
}
