import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function KpiTile({
  label,
  value,
  hint,
  alert,
}: {
  label: string
  value: ReactNode
  hint?: string
  alert?: boolean
}) {
  return (
    <div
      className={cn(
        'border-l-4 bg-white px-4 py-3 ring-1 ring-line',
        alert ? 'border-bad' : 'border-accent',
      )}
    >
      <p className="text-[11px] font-bold tracking-wide text-ink-muted uppercase">{label}</p>
      <p className={cn('mt-1 text-2xl font-bold tabular-nums', alert && 'text-bad')}>{value}</p>
      {hint && <p className="text-xs text-ink-muted">{hint}</p>}
    </div>
  )
}
