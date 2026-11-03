import { ArrowRight, RotateCcw, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { MIN_REASON } from '@/components/common/ReasonDialog'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Field, Select, Textarea } from '@/components/ui/form'
import { useApprovers } from '@/hooks/queries'
import type { CaseActions } from '@/hooks/useCaseActions'
import { formatInr } from '@/lib/format'
import { draftRoutingNote } from '@/lib/recommendation'
import type { Recommendation, RequestDetail } from '@/lib/types'
import { ClarifyButton } from './ClarifyButton'

const QUESTION_TYPES = new Set(['missing_info', 'ambiguity', 'conflict'])
const MANAGER_LIMIT_INR = 50_000

/**
 * Operations Team → Regional Manager hand-off. The team picks the manager (pre-selected by the
 * case region), sees open questions, and sends a note (pre-filled, editable) with the original
 * request.
 */
export function ForwardDialog({
  c,
  r,
  open,
  onOpenChange,
  actions,
}: {
  c: RequestDetail
  r: Recommendation
  open: boolean
  onOpenChange: (open: boolean) => void
  actions: CaseActions
}) {
  const approvers = useApprovers()
  const [chosen, setChosen] = useState('')
  const regional = approvers.data?.find((m) => m.region === c.region) ?? approvers.data?.[0]
  const approverId = chosen || regional?.id || ''
  const manager = approvers.data?.find((m) => m.id === approverId)
  // null = untouched: show the suggested note (it follows the chosen manager); text = edited.
  const [edited, setEdited] = useState<string | null>(null)
  const suggestion = draftRoutingNote(c, r, manager?.name)
  const note = edited ?? suggestion
  const questions = c.issues.filter((i) => i.status === 'open' && QUESTION_TYPES.has(i.type))
  const valid = note.trim().length >= MIN_REASON
  const close = (next: boolean) => {
    if (!next) setEdited(null)
    onOpenChange(next)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={close}
      title="Send for approval"
      description={`${r.title} · ${formatInr(r.estimated_cost_inr)}`}
      footer={
        <>
          <Button variant="ghost" onClick={() => close(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={!valid}
            loading={actions.select.isPending}
            onClick={() =>
              actions.select.mutate(
                { recId: r.id, note: note.trim(), approverId: approverId || undefined },
                { onSuccess: () => close(false) },
              )
            }
          >
            Send <ArrowRight />
          </Button>
        </>
      }
    >
      <div className="space-y-4 text-sm">
        <Field
          label="Regional Manager who decides"
          htmlFor="approver"
          hint={
            r.estimated_cost_inr > MANAGER_LIMIT_INR
              ? `Above ${formatInr(MANAGER_LIMIT_INR)}: the manager can only reject it or forward it to the Director.`
              : 'The manager approves, rejects, or forwards it to the Director.'
          }
        >
          <Select
            id="approver"
            value={approverId}
            onChange={(e) => setChosen(e.target.value)}
            disabled={!approvers.data}
          >
            {approvers.data?.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} · {m.region}
                {m.region === c.region ? ' (case region)' : ''}
              </option>
            ))}
          </Select>
        </Field>

        {questions.length > 0 && (
          <div className="border-l-4 border-warn bg-page px-3 py-2">
            <p className="flex items-center gap-1.5 font-bold">
              <TriangleAlert className="size-4 text-warn" /> {questions.length} open question(s)
            </p>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs">
              {questions.map((q) => (
                <li key={q.id}>{q.message}</li>
              ))}
            </ul>
            <div className="mt-2">
              <ClarifyButton c={c} actions={actions} onDone={() => close(false)} />
            </div>
          </div>
        )}

        <Field
          label="Note to the manager (sent with the original request)"
          htmlFor="routing-note"
          hint={
            edited === null
              ? 'Suggested from the case data — edit as needed before sending.'
              : 'Edited by you.'
          }
          error={!valid ? `Please write at least ${MIN_REASON} characters.` : undefined}
        >
          <Textarea
            id="routing-note"
            className="min-h-56"
            value={note}
            onChange={(e) => setEdited(e.target.value)}
          />
        </Field>
        {edited !== null && (
          <Button size="sm" variant="ghost" onClick={() => setEdited(null)}>
            <RotateCcw /> Reset to suggestion
          </Button>
        )}
      </div>
    </Dialog>
  )
}
