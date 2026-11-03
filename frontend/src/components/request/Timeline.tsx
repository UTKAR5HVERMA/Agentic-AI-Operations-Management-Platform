import { Bot, Cog, UserRound } from 'lucide-react'
import { QueryState } from '@/components/common/states'
import { useAudit } from '@/hooks/queries'
import { formatIst, formatPct } from '@/lib/format'
import type { AuditEntry } from '@/lib/types'

const ACTOR_ICON = { agent: Bot, human: UserRound, system: Cog }

function short(value: unknown): string {
  if (value === null || value === undefined) return ''
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return text.length > 160 ? `${text.slice(0, 160)}…` : text
}

function Entry({ e }: { e: AuditEntry }) {
  const Icon = ACTOR_ICON[e.actor_type]
  return (
    <li className="relative flex gap-3 pb-4 pl-1">
      <span className="z-10 flex size-7 shrink-0 items-center justify-center rounded-full bg-white ring-1 ring-line">
        <Icon className="size-3.5" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm">
          <b>{e.action}</b> <span className="text-ink-muted">by {e.actor}</span>
          {e.model && e.model !== 'deterministic' && (
            <span className="ml-2 text-xs text-ink-muted">· {e.model}</span>
          )}
          {e.confidence !== null && (
            <span className="ml-2 text-xs text-ink-muted">· conf {formatPct(e.confidence)}</span>
          )}
        </p>
        {e.reason && <p className="text-xs">Reason: {e.reason}</p>}
        {(e.before !== null || e.after !== null) && (
          <p className="mt-0.5 font-mono text-[11px] break-all text-ink-muted">
            {e.before !== null && (
              <>
                <s>{short(e.before)}</s> →{' '}
              </>
            )}
            {short(e.after)}
          </p>
        )}
        <p className="text-[11px] text-ink-muted">{formatIst(e.created_at)}</p>
      </div>
    </li>
  )
}

/** Audit rows for this case: every AI and human action, oldest first. */
export function Timeline({ requestId }: { requestId: string }) {
  const audit = useAudit({ request_id: requestId, limit: '500' })
  return (
    <QueryState query={audit}>
      {(rows) => (
        <ol className="relative before:absolute before:top-2 before:bottom-2 before:left-[17px] before:w-px before:bg-line">
          {[...rows].reverse().map((e) => (
            <Entry key={e.id} e={e} />
          ))}
        </ol>
      )}
    </QueryState>
  )
}
