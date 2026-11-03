import { Gauge } from 'lucide-react'
import { RiskBadge, SourceBadge } from '@/components/common/badges'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import type { RequestDetail, RiskAssessment } from '@/lib/types'
import { cn } from '@/lib/utils'

function Scale({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-14 text-ink-muted">{label}</span>
      <span className="flex gap-0.5" aria-label={`${label} ${value} of 5`}>
        {[1, 2, 3, 4, 5].map((i) => (
          <span key={i} className={cn('h-2 w-3', i <= value ? 'bg-ink' : 'bg-line')} />
        ))}
      </span>
      <span className="font-bold">{value}/5</span>
    </div>
  )
}

function RiskCard({
  title,
  r,
  highlight,
}: {
  title: string
  r: RiskAssessment
  highlight?: boolean
}) {
  return (
    <div
      className={cn(
        'flex flex-col gap-2 bg-white p-3 ring-1',
        highlight ? 'ring-2 ring-ink' : 'ring-line',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-bold tracking-wide uppercase">{title}</p>
        <RiskBadge level={r.risk_level} />
      </div>
      <Scale label="Urgency" value={r.urgency} />
      <Scale label="Impact" value={r.impact} />
      {r.factors.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-4 text-xs text-ink-muted">
          {r.factors.slice(0, 4).map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      )}
      <p className="text-xs leading-relaxed">{r.rationale}</p>
      {r.agent !== 'reconciled' && (
        <div className="mt-auto">
          <SourceBadge source={r.model === 'fallback' ? 'fallback' : 'agent'} />
        </div>
      )}
    </div>
  )
}

/** Two independent risk agents plus the deterministic reconciler (edge case 14). */
export function RiskPanel({ c }: { c: RequestDetail }) {
  const { ops, financial, reconciled } = c.risk
  if (!ops || !financial || !reconciled) return null
  return (
    <Card id="risk" className={cn(reconciled.disagreement && 'ring-2 ring-bad')}>
      <CardHeader
        title="Risk & impact"
        icon={<Gauge />}
        subtitle="Two independent agents; the reconciler takes the higher risk."
      />
      <CardBody className="space-y-3">
        {reconciled.disagreement && (
          <p className="border-l-4 border-bad bg-bad/5 px-3 py-2 text-sm font-bold text-bad">
            Agents disagreed ({ops.risk_level} vs {financial.risk_level}). Using the higher risk;
            human decision required.
          </p>
        )}
        <div className="grid gap-2 sm:grid-cols-2">
          <RiskCard title="Ops agent" r={ops} />
          <RiskCard title="Financial agent" r={financial} />
        </div>
        <RiskCard title="Reconciled (used for decisions)" r={reconciled} highlight />
      </CardBody>
    </Card>
  )
}
