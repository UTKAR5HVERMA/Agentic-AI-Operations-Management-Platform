import { Tooltip } from '@/components/ui/tooltip'
import { confidenceLevel } from '@/lib/confidence'
import { formatPct } from '@/lib/format'
import { cn } from '@/lib/utils'

type Breakdown = Partial<Record<'extraction' | 'data' | 'risk' | 'recommendation', number>>

const PARTS: [keyof Breakdown, string, number][] = [
  ['extraction', 'Extraction (grounded fields)', 0.4],
  ['data', 'Data agreement (inventory)', 0.2],
  ['risk', 'Risk agents agreement', 0.2],
  ['recommendation', 'Recommendation evidence', 0.2],
]

interface Props {
  value: number
  breakdown?: Breakdown
  compact?: boolean
  className?: string
}

export function ConfidenceMeter({ value, breakdown, compact, className }: Props) {
  const level = confidenceLevel(value)
  const meter = (
    <div
      className={cn('flex min-w-28 items-center gap-2', className)}
      aria-label={`Confidence ${formatPct(value)} ${level.label}`}
    >
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-line">
        <div className={cn('h-full', level.bar)} style={{ width: `${Math.round(value * 100)}%` }} />
      </div>
      <span className={cn('text-xs font-bold tabular-nums', level.tone)}>
        {formatPct(value)}
        {!compact && <span className="ml-1 font-normal">{level.label}</span>}
      </span>
    </div>
  )
  if (!breakdown) return meter
  return (
    <Tooltip
      content={
        <div className="space-y-1">
          <p className="font-bold">How confidence is computed</p>
          {PARTS.map(([key, label, weight]) => (
            <p key={key} className="flex justify-between gap-4">
              <span>
                {label} ×{weight}
              </span>
              <span className="tabular-nums">{formatPct(breakdown[key] ?? 0)}</span>
            </p>
          ))}
          <p className="pt-1 text-white/70">Never the LLM&apos;s self-report alone.</p>
        </div>
      }
    >
      <button type="button" className="cursor-help">
        {meter}
      </button>
    </Tooltip>
  )
}
