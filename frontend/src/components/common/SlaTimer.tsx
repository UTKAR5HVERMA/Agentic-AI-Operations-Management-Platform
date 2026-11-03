import { Clock } from 'lucide-react'
import { useCountdown } from '@/hooks/useCountdown'
import { formatDuration, formatIst } from '@/lib/format'
import { cn } from '@/lib/utils'

const TWO_HOURS = 2 * 3_600_000
const THIRTY_MIN = 30 * 60_000

export function SlaTimer({ target, done = false }: { target: string | null; done?: boolean }) {
  const remaining = useCountdown(done ? null : target)
  if (!target) return <span className="text-ink-muted">—</span>
  if (done || remaining === null) return <span className="text-ink-muted">{formatIst(target)}</span>
  const overdue = remaining < 0
  const tone =
    overdue || remaining < THIRTY_MIN
      ? 'text-bad'
      : remaining < TWO_HOURS
        ? 'text-[#a85700]'
        : 'text-ink'
  return (
    <span
      title={formatIst(target)}
      className={cn(
        'inline-flex items-center gap-1 font-bold tabular-nums whitespace-nowrap',
        tone,
        overdue && 'animate-pulse-soft',
      )}
    >
      <Clock className="size-3.5" />
      {overdue ? `Overdue by ${formatDuration(remaining)}` : `${formatDuration(remaining)} left`}
    </span>
  )
}
