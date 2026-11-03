import { useMutation } from '@tanstack/react-query'
import { Bot, ChevronRight, Cog, ShieldCheck, ShieldX, UserRound } from 'lucide-react'
import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { PageHeader, QueryState } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input, Select } from '@/components/ui/form'
import { Table, Td, Th, Tr } from '@/components/ui/table'
import { useAudit } from '@/hooks/queries'
import { api, errorMessage } from '@/lib/api'
import { formatIst, formatPct } from '@/lib/format'
import type { AuditEntry, AuditVerify } from '@/lib/types'
import { cn } from '@/lib/utils'

const ICON = { agent: Bot, human: UserRound, system: Cog }

function Detail({ e }: { e: AuditEntry }) {
  const meta = [
    e.model && `Model ${e.model}`,
    e.prompt_hash && `Prompt ${e.prompt_hash.slice(0, 12)}…`,
    e.latency_ms !== null && `${e.latency_ms} ms`,
    e.tokens !== null && `${e.tokens} tokens`,
    e.confidence !== null && `Confidence ${formatPct(e.confidence)}`,
    e.ip && `IP ${e.ip}`,
  ].filter(Boolean)
  return (
    <div className="grid gap-3 bg-page p-3 md:grid-cols-2">
      {(['before', 'after'] as const).map((k) => (
        <div key={k}>
          <p className="mb-1 text-[11px] font-bold text-ink-muted uppercase">{k}</p>
          <pre className="max-h-48 overflow-auto bg-white p-2 font-mono text-[11px] ring-1 ring-line">
            {JSON.stringify(e[k], null, 2) ?? '—'}
          </pre>
        </div>
      ))}
      <p className="text-xs text-ink-muted md:col-span-2">
        {meta.join(' · ')} · hash {e.hash.slice(0, 16)}…
      </p>
    </div>
  )
}

export default function AuditPage() {
  const [filters, setFilters] = useState<Record<string, string | undefined>>({})
  const [open, setOpen] = useState<number | null>(null)
  const audit = useAudit(filters)
  const verify = useMutation({
    mutationFn: () => api<AuditVerify>('/audit/verify'),
    onError: (e) => toast.error(errorMessage(e)),
  })
  const set = (k: string) => (e: { target: { value: string } }) =>
    setFilters((f) => ({ ...f, [k]: e.target.value || undefined }))
  const v = verify.data

  return (
    <>
      <PageHeader
        title="Audit trail"
        subtitle="Append-only, hash-chained record of every AI and human action"
        actions={
          <Button variant="dark" loading={verify.isPending} onClick={() => verify.mutate()}>
            <ShieldCheck /> Verify integrity
          </Button>
        }
      />
      {v && (
        <div
          className={cn(
            'mb-4 flex items-center gap-2 border-l-4 px-4 py-3 font-bold ring-1 ring-line',
            v.valid ? 'border-ok bg-ok/5 text-ok' : 'border-bad bg-bad/5 text-bad',
          )}
          role="status"
        >
          {v.valid ? <ShieldCheck className="size-5" /> : <ShieldX className="size-5" />}
          {v.valid
            ? `Audit chain valid · ${v.rows.toLocaleString('en-IN')} entries`
            : `Chain broken at entry #${v.broken_at_id} — tampering detected`}
        </div>
      )}
      <Card>
        <div className="flex flex-wrap gap-3 border-b border-line p-3">
          <Select aria-label="Actor type" className="w-36" onChange={set('actor_type')}>
            <option value="">All actors</option>
            <option value="agent">AI agent</option>
            <option value="human">Human</option>
            <option value="system">System</option>
          </Select>
          <Input
            aria-label="Action prefix"
            className="w-56"
            placeholder="Action (e.g. approval.)"
            onChange={set('action')}
          />
          <Input
            aria-label="Actor"
            className="w-56"
            placeholder="Actor (email or agent)"
            onChange={set('actor')}
          />
          <Input
            aria-label="From date"
            type="date"
            className="w-40"
            onChange={(e) =>
              setFilters((f) => ({
                ...f,
                since: e.target.value ? `${e.target.value}T00:00:00+05:30` : undefined,
              }))
            }
          />
          <Input
            aria-label="To date"
            type="date"
            className="w-40"
            onChange={(e) =>
              setFilters((f) => ({
                ...f,
                until: e.target.value ? `${e.target.value}T23:59:59+05:30` : undefined,
              }))
            }
          />
        </div>
        <QueryState query={audit}>
          {(rows) => (
            <Table>
              <thead>
                <tr>
                  <Th className="w-8" />
                  <Th>#</Th>
                  <Th>Time</Th>
                  <Th>Case</Th>
                  <Th>Actor</Th>
                  <Th>Action</Th>
                  <Th>Reason</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => {
                  const Icon = ICON[e.actor_type]
                  return (
                    <Fragment key={e.id}>
                      <Tr
                        className="cursor-pointer"
                        onClick={() => setOpen(open === e.id ? null : e.id)}
                      >
                        <Td>
                          <ChevronRight
                            className={cn(
                              'size-4 transition-transform',
                              open === e.id && 'rotate-90',
                            )}
                          />
                        </Td>
                        <Td className="tabular-nums text-ink-muted">{e.id}</Td>
                        <Td className="whitespace-nowrap">{formatIst(e.created_at)}</Td>
                        <Td className="whitespace-nowrap">
                          {e.request_ref ? (
                            <Link
                              className="font-bold hover:underline"
                              to={`/requests/${e.request_id}`}
                              onClick={(ev) => ev.stopPropagation()}
                            >
                              {e.request_ref}
                            </Link>
                          ) : (
                            '—'
                          )}
                        </Td>
                        <Td className="whitespace-nowrap">
                          <Icon className="mr-1 inline size-3.5" />
                          {e.actor}
                        </Td>
                        <Td className="font-bold">{e.action}</Td>
                        <Td className="max-w-72 truncate text-ink-muted">{e.reason ?? ''}</Td>
                      </Tr>
                      {open === e.id && (
                        <tr>
                          <td colSpan={7}>
                            <Detail e={e} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </Table>
          )}
        </QueryState>
      </Card>
    </>
  )
}
