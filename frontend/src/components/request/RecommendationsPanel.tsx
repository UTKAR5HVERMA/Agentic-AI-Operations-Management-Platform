import { Lightbulb, PenLine, Sparkles } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'
import { EmptyState } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import type { CaseActions } from '@/hooks/useCaseActions'
import { clarifyQuestions, openClarification } from '@/lib/caseFlow'
import { formatInr } from '@/lib/format'
import { approvalLabel, timing } from '@/lib/recommendation'
import type { Recommendation, RequestDetail } from '@/lib/types'
import { ClarifyActionCard } from './ClarifyActionCard'
import { OverrideDialog } from './OverrideDialog'
import { ChooseButton, OptionRow } from './RecommendationOption'

const INACTIVE = new Set(['rejected', 'superseded', 'overridden'])

function Section({
  n,
  title,
  hint,
  children,
}: {
  n: number
  title: string
  hint: string
  children: ReactNode
}) {
  return (
    <section className="space-y-2">
      <div className="flex items-baseline gap-2">
        <span className="flex size-5 items-center justify-center rounded-full bg-ink text-[11px] font-bold text-white">
          {n}
        </span>
        <h3 className="text-sm">{title}</h3>
        <span className="text-xs text-ink-muted">{hint}</span>
      </div>
      {children}
    </section>
  )
}

/** The AI's pick in one sentence: what it does, what it solves, cost, time, who approves. */
function TopPick({ c, r, actions }: { c: RequestDetail; r: Recommendation; actions: CaseActions }) {
  const when = timing(r, c.deadline_at)
  return (
    <div className="border border-ink border-l-4 border-l-accent bg-white px-4 py-3">
      <p className="flex items-center gap-1.5 text-[11px] font-bold tracking-widest text-ink-muted uppercase">
        <Sparkles className="size-3.5" /> AI recommends
      </p>
      <p className="mt-1 text-base font-bold">{r.title}</p>
      <p className="mt-1 text-sm">
        {r.risk_reduction} Costs <b>{formatInr(r.estimated_cost_inr)}</b>, ready in{' '}
        <b>
          {r.estimated_lead_time_days} day{r.estimated_lead_time_days === 1 ? '' : 's'}
        </b>
        {when === 'in time' && ' (before the deadline)'}
        {when === 'late' && <span className="text-bad"> (after the deadline)</span>}. Approval:{' '}
        <b>{approvalLabel(r)}</b>.
      </p>
      {r.rationale && <p className="mt-1 text-sm text-ink-muted">{r.rationale}</p>}
      <div className="mt-3">
        <ChooseButton c={c} r={r} actions={actions} primary />
      </div>
    </div>
  )
}

export function RecommendationsPanel({ c, actions }: { c: RequestDetail; actions: CaseActions }) {
  const [overriding, setOverriding] = useState(false)
  const [showOld, setShowOld] = useState(false)
  const can = (a: string) => c.allowed_actions.includes(a)
  const active = c.recommendations.filter((r) => !INACTIVE.has(r.status))
  const old = c.recommendations.filter((r) => INACTIVE.has(r.status))
  const top = active.find((r) => r.status === 'proposed' && r.created_by === 'agent') ?? active[0]
  // Same condition as ClarifyActionCard, so the section never renders empty.
  const askFirst = clarifyQuestions(c).length > 0 || openClarification(c) !== undefined
  const first = askFirst ? 2 : 1 // section numbers: ask first (optional) → pick → compare

  return (
    <Card>
      <CardHeader
        title="Recommended actions"
        icon={<Lightbulb />}
        subtitle="Costs and lead times come from inventory and supplier data; the AI only ranks and explains. A human always chooses."
        actions={
          can('override') && (
            <Button size="sm" onClick={() => setOverriding(true)}>
              <PenLine /> Propose my own option
            </Button>
          )
        }
      />
      <CardBody className="space-y-5">
        {askFirst && (
          <Section n={1} title="Before you decide" hint="answers could change the best option">
            <ClarifyActionCard c={c} actions={actions} />
          </Section>
        )}
        {active.length === 0 ? (
          <EmptyState
            title="No recommendation"
            hint={
              c.confidence_band === 'withheld'
                ? 'Withheld: not enough evidence to recommend safely. Ask the requester first.'
                : 'Recommendations appear once the case has enough information.'
            }
          />
        ) : (
          <>
            {top && (
              <Section n={first} title="Recommended option" hint="the AI's first choice">
                <TopPick c={c} r={top} actions={actions} />
              </Section>
            )}
            <Section
              n={top ? first + 1 : first}
              title="Compare all options"
              hint="choose any one; your choice is audited"
            >
              <div className="overflow-x-auto border border-line">
                <div className="grid min-w-[760px] grid-cols-[2rem_minmax(0,2.4fr)_minmax(0,1.6fr)_6rem_6rem_minmax(0,1.3fr)] gap-3 border-b border-line bg-page px-4 py-2 text-[11px] font-bold tracking-wide text-ink-muted uppercase">
                  <span>#</span>
                  <span>Option</span>
                  <span>Solves the problem?</span>
                  <span>Cost</span>
                  <span>Ready in</span>
                  <span>Approval</span>
                </div>
                <ol className="min-w-[760px]">
                  {active.map((r) => (
                    <OptionRow key={r.id} c={c} r={r} actions={actions} top={r.id === top?.id} />
                  ))}
                </ol>
              </div>
            </Section>
          </>
        )}
        {old.length > 0 && (
          <div>
            <button
              type="button"
              className="text-xs font-bold text-ink-muted hover:text-ink"
              onClick={() => setShowOld((s) => !s)}
            >
              {showOld ? 'Hide' : 'Show'} {old.length} earlier option(s) (rejected, superseded or
              overridden)
            </button>
            {showOld && (
              <ol className="mt-2 border border-line">
                {old.map((r) => (
                  <OptionRow key={r.id} c={c} r={r} actions={actions} top={false} />
                ))}
              </ol>
            )}
          </div>
        )}
      </CardBody>
      <OverrideDialog
        open={overriding}
        onOpenChange={setOverriding}
        actions={actions}
        region={c.region}
      />
    </Card>
  )
}
