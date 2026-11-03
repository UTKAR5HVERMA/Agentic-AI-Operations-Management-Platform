import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Play, RotateCcw, Timer } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { PageHeader, QueryState } from '@/components/common/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Switch } from '@/components/ui/form'
import { useFlags } from '@/hooks/queries'
import { useAuth } from '@/lib/auth'
import { errorMessage, post, put } from '@/lib/api'
import { SCENARIOS } from '@/lib/scenarios'
import type { Flags, TickResult } from '@/lib/types'

const FLAG_LABELS: { key: keyof Flags; label: string; hint: string }[] = [
  { key: 'llm_down', label: 'LLM down', hint: 'Agents fall back to rules; cases marked Degraded.' },
  {
    key: 'inventory_down',
    label: 'Inventory down',
    hint: 'Validation uses the email value at 50% confidence.',
  },
  {
    key: 'email_down',
    label: 'Email down',
    hint: 'Sends fail and retry with backoff, then in-app.',
  },
]

export default function ScenarioLabPage() {
  const navigate = useNavigate()
  const client = useQueryClient()
  const { logout } = useAuth()
  const flags = useFlags()
  const [running, setRunning] = useState<string | null>(null)
  const [confirmReset, setConfirmReset] = useState(false)
  const refresh = () => client.invalidateQueries()
  const onError = (e: unknown) => toast.error(errorMessage(e))

  const toggle = useMutation({
    mutationFn: (patch: Partial<Flags>) => put<Flags>('/admin/flags', patch),
    onSuccess: refresh,
    onError,
  })
  const tick = useMutation({
    mutationFn: () => post<TickResult>('/simulate/scheduler-tick'),
    onSuccess: (r) => {
      refresh()
      toast.success(
        `Scheduler: ${r.escalations} escalations, ${r.retries} retries, ${r.reanalyzed} re-analysed, ${r.reminders} reminders`,
      )
    },
    onError,
  })
  const reset = useMutation({
    mutationFn: () => post('/admin/reset-demo'),
    // Users are re-created with new ids, so the current session ends.
    onSuccess: () => {
      toast.success('Demo data reset — please sign in again')
      logout()
    },
    onError,
  })

  const run = async (id: string, fn: () => Promise<string>) => {
    setRunning(id)
    try {
      const caseId = await fn()
      await refresh()
      navigate(`/requests/${caseId}`)
    } catch (e) {
      onError(e)
    } finally {
      setRunning(null)
    }
  }

  return (
    <>
      <PageHeader
        title="Scenario Lab"
        subtitle="Demo cockpit: inject faults and launch edge cases in one click"
        actions={
          <>
            <Button onClick={() => tick.mutate()} loading={tick.isPending}>
              <Timer /> Run scheduler tick
            </Button>
            <Button variant="danger" onClick={() => setConfirmReset(true)}>
              <RotateCcw /> Reset demo data
            </Button>
          </>
        }
      />
      <Card className="mb-5">
        <CardHeader
          title="System toggles"
          subtitle="Simulate outages of dependent systems (edge cases 10 & 13)"
        />
        <CardBody>
          <QueryState query={flags}>
            {(f) => (
              <div className="grid gap-4 md:grid-cols-3">
                {FLAG_LABELS.map(({ key, label, hint }) => (
                  <label key={key} className="flex items-start gap-3 border border-line p-3">
                    <Switch
                      checked={f[key]}
                      disabled={toggle.isPending}
                      onCheckedChange={(v) => toggle.mutate({ [key]: v })}
                      aria-label={label}
                    />
                    <span>
                      <span className="flex items-center gap-2 font-bold">
                        {label} {f[key] && <Badge tone="bad">active</Badge>}
                      </span>
                      <span className="text-xs text-ink-muted">{hint}</span>
                    </span>
                  </label>
                ))}
              </div>
            )}
          </QueryState>
        </CardBody>
      </Card>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {SCENARIOS.map((s) => (
          <Card key={s.id} className="flex flex-col">
            <div className="flex flex-1 flex-col gap-2 p-4">
              <div className="flex items-center justify-between">
                <h3 className="text-[15px]">{s.title}</h3>
                <Badge tone="accent">Edge {s.edge}</Badge>
              </div>
              <p className="flex-1 text-sm text-ink-muted">{s.description}</p>
              <Button
                size="sm"
                variant="dark"
                className="self-start"
                loading={running === s.id}
                disabled={running !== null}
                onClick={() => run(s.id, s.run)}
              >
                <Play /> Run
              </Button>
            </div>
          </Card>
        ))}
      </div>
      <Dialog
        open={confirmReset}
        onOpenChange={setConfirmReset}
        title="Reset demo data?"
        description="Wipes every case, approval and audit row, then reseeds users, inventory and suppliers."
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmReset(false)}>
              Cancel
            </Button>
            <Button variant="danger" loading={reset.isPending} onClick={() => reset.mutate()}>
              Reset everything
            </Button>
          </>
        }
      >
        <p>This cannot be undone. The audit chain restarts with a reset record.</p>
      </Dialog>
    </>
  )
}
