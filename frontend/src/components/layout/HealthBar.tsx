import { AlertTriangle } from 'lucide-react'
import { Tooltip } from '@/components/ui/tooltip'
import { useHealth } from '@/hooks/queries'
import { useAuth } from '@/lib/auth'
import { ROLE_LABEL } from '@/lib/labels'
import type { Health } from '@/lib/types'
import { cn } from '@/lib/utils'

const DOT: Record<string, string> = { up: 'bg-ok', fallback: 'bg-warn', down: 'bg-bad' }

function Indicator({ label, state, hint }: { label: string; state: string; hint: string }) {
  return (
    <Tooltip content={hint}>
      <span className="inline-flex cursor-default items-center gap-1.5 text-xs">
        <span className={cn('size-2 rounded-full', DOT[state] ?? 'bg-line-strong')} />
        <span className="text-ink-muted">{label}</span>
        <span className="font-bold capitalize">{state}</span>
      </span>
    </Tooltip>
  )
}

function outageMessage(h: Health): string | null {
  const down = [
    h.llm === 'down' && 'LLM',
    h.inventory === 'down' && 'Inventory system',
    h.email === 'down' && 'Email service',
  ].filter(Boolean)
  if (!down.length) return null
  return `${down.join(', ')} unavailable — AI is using fallback data and affected cases are marked Degraded.`
}

/** Top bar: live system status (edge case 10). Polls /api/health every 15 s. */
export function HealthBar() {
  const { user } = useAuth()
  const health = useHealth()
  const h = health.data
  const banner = h ? outageMessage(h) : health.isError ? 'Cannot reach the OpsPilot server.' : null

  return (
    <header>
      <div className="flex h-12 items-center justify-between border-b border-line bg-white px-6">
        <div className="flex items-center gap-5">
          {h ? (
            <>
              <Indicator
                label="LLM"
                state={h.llm}
                hint={
                  h.llm === 'fallback'
                    ? 'No LLM key / mock mode: rule-based engine in use'
                    : `Model: ${h.model}`
                }
              />
              <Indicator label="Inventory" state={h.inventory} hint="Inventory system of record" />
              <Indicator label="Email" state={h.email} hint="Notification / email service" />
            </>
          ) : (
            <span className="text-xs text-ink-muted">Checking systems…</span>
          )}
        </div>
        {user && (
          <span className="text-xs text-ink-muted">
            Signed in as <b className="text-ink">{user.name}</b> · {ROLE_LABEL[user.role]}
          </span>
        )}
      </div>
      {banner && (
        <div
          className="flex items-center gap-2 border-b border-warn/40 bg-warn/15 px-6 py-1.5 text-xs font-bold text-[#8a4600]"
          role="status"
        >
          <AlertTriangle className="size-3.5" /> {banner}
        </div>
      )}
    </header>
  )
}
