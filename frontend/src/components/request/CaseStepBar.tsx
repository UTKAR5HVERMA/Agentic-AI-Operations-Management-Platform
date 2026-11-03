import { ArrowRight, Check, CircleAlert, OctagonAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { STEPS } from '@/lib/caseFlow'
import type { NextStep, StepId, StepStatus } from '@/lib/caseFlow'
import { cn } from '@/lib/utils'

const MARK = {
  done: { icon: Check, cls: 'bg-ok text-white' },
  attention: { icon: CircleAlert, cls: 'bg-warn text-ink' },
  blocked: { icon: OctagonAlert, cls: 'bg-bad text-white' },
  idle: { icon: null, cls: 'bg-page text-ink-muted ring-1 ring-line' },
} as const

/** Numbered workflow steps; one is shown at a time so the page reads top to bottom. */
export function CaseStepBar({
  active,
  status,
  onSelect,
}: {
  active: StepId
  status: Record<StepId, StepStatus>
  onSelect: (step: StepId) => void
}) {
  // -top-6 + pt-6: stick to the scroll area's very top edge (above <main>'s py-6 padding) and
  // paint over that padding, so content never shows through the gap while scrolling.
  return (
    <nav
      aria-label="Case workflow"
      className="sticky -top-6 z-20 -mx-1 mb-4 overflow-x-auto bg-page px-1 pt-6 pb-2 shadow-[0_6px_6px_-6px_rgb(0_0_0/0.15)]"
    >
      <ol className="flex min-w-max gap-1 border-b border-line">
        {STEPS.map((step, i) => {
          const s = status[step.id]
          const { icon: Icon, cls } = MARK[s.state]
          const current = step.id === active
          return (
            <li key={step.id}>
              <button
                type="button"
                onClick={() => onSelect(step.id)}
                aria-current={current ? 'step' : undefined}
                className={cn(
                  '-mb-px flex items-center gap-2 border-b-[3px] px-3 py-2 text-left',
                  current ? 'border-accent' : 'border-transparent hover:border-line-strong',
                )}
              >
                <span
                  className={cn(
                    'flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-bold',
                    cls,
                  )}
                >
                  {Icon ? <Icon className="size-3.5" /> : i + 1}
                </span>
                <span>
                  <span className={cn('block text-sm font-bold', !current && 'text-ink-muted')}>
                    {step.label}
                  </span>
                  <span className="block text-[11px] text-ink-muted">{s.badge ?? step.hint}</span>
                </span>
              </button>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

/** "What should I do now?" — derived from status, open issues and the user's allowed actions. */
export function NextStepBar({
  next,
  active,
  onGo,
}: {
  next: NextStep
  active: StepId
  onGo: (step: StepId) => void
}) {
  const label = STEPS.find((s) => s.id === next.step)?.label
  return (
    <div className="flex flex-wrap items-center gap-3 border-l-4 border-accent bg-white px-4 py-3 ring-1 ring-line">
      <div className="min-w-0 flex-1">
        <p className="text-[11px] font-bold tracking-widest text-ink-muted uppercase">Next step</p>
        <p className="font-bold">{next.title}</p>
        {next.detail && <p className="text-sm text-ink-muted">{next.detail}</p>}
      </div>
      {next.step !== active && (
        <Button size="sm" variant="dark" onClick={() => onGo(next.step)}>
          Go to {label} <ArrowRight />
        </Button>
      )}
    </div>
  )
}
