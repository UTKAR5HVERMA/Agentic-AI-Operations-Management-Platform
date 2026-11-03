import { MessagesSquare, RefreshCw, Send, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { SourceBadge } from '@/components/common/badges'
import { Badge } from '@/components/ui/badge'
import type { BadgeTone } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Field, Input, Select, Textarea } from '@/components/ui/form'
import type { CaseActions } from '@/hooks/useCaseActions'
import { useCaseNav } from '@/hooks/useCaseNav'
import { formatIst, titleCase } from '@/lib/format'
import type { Communication, CommType, RequestDetail } from '@/lib/types'

const GENERATE: { value: CommType; label: string }[] = [
  { value: 'stakeholder_update', label: 'Stakeholder update' },
  { value: 'clarification', label: 'Clarification request' },
  { value: 'escalation', label: 'Escalation' },
  { value: 'closure', label: 'Closure notice' },
]

function statusBadge(m: Communication): { tone: BadgeTone; label: string } {
  if (m.status === 'sent') return { tone: 'ok', label: 'Sent' }
  if (m.status === 'failed')
    return m.delivered_via === 'in_app'
      ? { tone: 'bad', label: 'Failed · in-app fallback' }
      : { tone: 'bad', label: `Retrying ${m.attempts}/3` }
  return { tone: 'neutral', label: titleCase(m.status) }
}

function Editor({
  m,
  actions,
  onClose,
  onDelete,
}: {
  m: Communication
  actions: CaseActions
  onClose: () => void
  onDelete: () => void
}) {
  const [subject, setSubject] = useState(m.subject)
  const [body, setBody] = useState(m.body)
  const [to, setTo] = useState(m.to.join(', '))
  const editable = m.status === 'draft' || m.status === 'failed'
  const recipients = to
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  const dirty = subject !== m.subject || body !== m.body || to !== m.to.join(', ')
  const save = () => actions.updateComm.mutateAsync({ id: m.id, subject, body, to: recipients })
  const send = async () => {
    if (dirty) await save()
    actions.sendComm.mutate(m.id, { onSuccess: onClose })
  }
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      side="right"
      title={titleCase(m.type)}
      description="AI drafts never send themselves — a human approves every message."
      footer={
        editable && (
          <>
            <Button variant="danger" className="mr-auto" onClick={onDelete}>
              <Trash2 /> Delete draft
            </Button>
            <Button disabled={!dirty} loading={actions.updateComm.isPending} onClick={() => save()}>
              Save
            </Button>
            <Button
              variant="primary"
              disabled={!recipients.length}
              loading={actions.sendComm.isPending}
              onClick={send}
            >
              <Send /> {m.status === 'failed' ? 'Retry now' : 'Approve & send'}
            </Button>
          </>
        )
      }
    >
      <div className="space-y-4">
        <div className="flex flex-wrap gap-2">
          <SourceBadge source={m.edited ? 'human' : m.model === 'template' ? 'system' : 'agent'} />
          {m.edited && <Badge>Edited</Badge>}
        </div>
        {m.last_error && (
          <p className="border-l-4 border-bad bg-bad/5 px-3 py-2 text-sm text-bad">
            {m.last_error}
            {m.next_retry_at && ` · auto-retry at ${formatIst(m.next_retry_at)}`}
          </p>
        )}
        <Field label="To (comma separated)" htmlFor="comm-to">
          <Input
            id="comm-to"
            value={to}
            disabled={!editable}
            onChange={(e) => setTo(e.target.value)}
          />
        </Field>
        <Field label="Subject" htmlFor="comm-subject">
          <Input
            id="comm-subject"
            value={subject}
            disabled={!editable}
            onChange={(e) => setSubject(e.target.value)}
          />
        </Field>
        <Field label="Message" htmlFor="comm-body">
          <Textarea
            id="comm-body"
            className="min-h-72"
            value={body}
            disabled={!editable}
            onChange={(e) => setBody(e.target.value)}
          />
        </Field>
      </div>
    </Dialog>
  )
}

const UNSENT = new Set(['draft', 'failed'])

function DeleteDialog({
  m,
  actions,
  onClose,
}: {
  m: Communication
  actions: CaseActions
  onClose: () => void
}) {
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title="Delete this draft?"
      description={m.subject}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Keep it
          </Button>
          <Button
            variant="danger"
            loading={actions.discardComm.isPending}
            onClick={() => actions.discardComm.mutate(m.id, { onSuccess: onClose })}
          >
            <Trash2 /> Delete draft
          </Button>
        </>
      }
    >
      <p className="text-sm">
        It is removed from this case and never sent. The audit trail keeps a record that it was
        deleted. You can draft a new one at any time.
      </p>
    </Dialog>
  )
}

export function CommunicationsPanel({ c, actions }: { c: RequestDetail; actions: CaseActions }) {
  const nav = useCaseNav()
  const [localId, setLocalId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<Communication | null>(null)
  // The case view can open a draft from elsewhere ("Clarification drafted — view").
  const openId = nav ? nav.openCommId : localId
  const setOpenId = (id: string | null) =>
    nav ? (id ? nav.openComm(id) : nav.closeComm()) : setLocalId(id)
  const opened = c.communications.find((m) => m.id === openId)
  const canGenerate = c.allowed_actions.includes('generate_comm')
  return (
    <Card>
      <CardHeader
        title="Messages"
        icon={<MessagesSquare />}
        subtitle="Drafts, approval requests and delivery status. Nothing is sent without a human."
        actions={
          canGenerate && (
            <Select
              aria-label="Generate draft"
              className="h-8 w-44 text-xs"
              value=""
              onChange={(e) =>
                e.target.value && actions.generateComm.mutate(e.target.value as CommType)
              }
            >
              <option value="">+ Generate draft…</option>
              {GENERATE.map((g) => (
                <option key={g.value} value={g.value}>
                  {g.label}
                </option>
              ))}
            </Select>
          )
        }
      />
      <ul className="divide-y divide-line">
        {c.communications.length === 0 && (
          <li className="px-4 py-6 text-center text-ink-muted">No messages yet.</li>
        )}
        {[...c.communications].reverse().map((m) => {
          const s = statusBadge(m)
          return (
            <li key={m.id} className="flex items-center pr-2">
              <button
                type="button"
                className="flex w-full items-start gap-3 px-4 py-2.5 text-left hover:bg-page"
                onClick={() => setOpenId(m.id)}
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate font-bold">{m.subject}</p>
                  <p className="truncate text-xs text-ink-muted">
                    {titleCase(m.type)} · to {m.to.join(', ') || '—'}
                  </p>
                </div>
                <Badge tone={s.tone}>
                  {m.status === 'failed' && m.delivered_via !== 'in_app' && (
                    <RefreshCw className="animate-spin" />
                  )}
                  {s.label}
                </Badge>
              </button>
              {UNSENT.has(m.status) && canGenerate && (
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Delete draft ${m.subject}`}
                  title="Delete draft"
                  onClick={() => setDeleting(m)}
                >
                  <Trash2 />
                </Button>
              )}
            </li>
          )
        })}
      </ul>
      {opened && (
        <Editor
          key={opened.id}
          m={opened}
          actions={actions}
          onClose={() => setOpenId(null)}
          onDelete={() => {
            setOpenId(null)
            setDeleting(opened)
          }}
        />
      )}
      {deleting && (
        <DeleteDialog m={deleting} actions={actions} onClose={() => setDeleting(null)} />
      )}
    </Card>
  )
}
