import { Check, Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'

const PIPELINE_STEPS = [
  'Intake & safety',
  'Extraction',
  'Validation & duplicates',
  'Risk (2 agents)',
  'Recommendations',
  'Approval routing',
  'Drafts',
]

/** Animated progress while the synchronous analysis call runs (FRONTEND.md §5.4). */
export function AgentStepper({ done }: { done: boolean }) {
  const [active, setActive] = useState(0)
  useEffect(() => {
    if (done) return
    const id = window.setInterval(
      () => setActive((i) => Math.min(i + 1, PIPELINE_STEPS.length - 1)),
      900,
    )
    return () => window.clearInterval(id)
  }, [done])
  const current = done ? PIPELINE_STEPS.length : active

  return (
    <ol className="space-y-2" aria-live="polite">
      {PIPELINE_STEPS.map((step, i) => {
        const complete = i < current
        const running = i === current
        return (
          <li key={step} className="flex items-center gap-3">
            <span
              className={cn(
                'flex size-6 items-center justify-center rounded-full border text-xs font-bold',
                complete && 'border-ink bg-ink text-accent',
                running && 'border-ink bg-accent text-ink',
                !complete && !running && 'border-line-strong text-ink-muted',
              )}
            >
              {complete ? (
                <Check className="size-3.5" />
              ) : running ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                i + 1
              )}
            </span>
            <span className={cn(complete || running ? 'font-bold text-ink' : 'text-ink-muted')}>
              {step}
            </span>
          </li>
        )
      })}
    </ol>
  )
}
