import { Bot, CheckCircle2, CircleAlert, Cog } from 'lucide-react'
import { Card, CardHeader } from '@/components/ui/card'
import { AGENT_LABEL } from '@/lib/labels'
import type { RequestDetail } from '@/lib/types'

/** Which agent ran, on which model, how long, and whether it fell back. */
export function AgentTracePanel({ c }: { c: RequestDetail }) {
  const total = c.agent_trace.reduce((sum, t) => sum + t.ms, 0)
  return (
    <Card>
      <CardHeader
        title="Agent trace"
        icon={<Bot />}
        subtitle={`${c.agent_trace.length} agents · ${(total / 1000).toFixed(1)} s total (latest run)`}
      />
      <ol className="divide-y divide-line">
        {c.agent_trace.map((t, i) => {
          const llm = t.model !== 'deterministic'
          return (
            <li key={`${t.agent}-${i}`} className="flex items-center gap-3 px-4 py-2 text-sm">
              {t.ok ? (
                <CheckCircle2 className="size-4 text-ok" />
              ) : (
                <CircleAlert className="size-4 text-warn" />
              )}
              <span className="flex-1 font-bold">{AGENT_LABEL[t.agent] ?? t.agent}</span>
              <span
                className="inline-flex items-center gap-1 text-xs text-ink-muted"
                title={t.error ?? undefined}
              >
                {llm ? <Bot className="size-3.5" /> : <Cog className="size-3.5" />}
                {t.model === 'deterministic' ? 'rules' : t.model}
              </span>
              <span className="w-14 text-right text-xs tabular-nums text-ink-muted">{t.ms} ms</span>
            </li>
          )
        })}
      </ol>
    </Card>
  )
}
