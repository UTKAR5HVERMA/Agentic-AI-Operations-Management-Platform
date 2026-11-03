import { useMutation } from '@tanstack/react-query'
import { ArrowLeft, Reply, Send, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Field, Textarea } from '@/components/ui/form'
import type { CaseActions } from '@/hooks/useCaseActions'
import { errorMessage, post } from '@/lib/api'
import type { RequestDetail } from '@/lib/types'

interface Composed {
  body: string
  model: string
  note: string | null
}

/**
 * Requester → Operations Team reply. Write a rough answer, let the AI turn it into a clear reply
 * (no new facts or numbers), edit it, send it. The case re-analyses with the answer.
 */
export function RequesterReply({
  c,
  actions,
  hint,
}: {
  c: RequestDetail
  actions: CaseActions
  hint?: string
}) {
  const [notes, setNotes] = useState('')
  const [draft, setDraft] = useState<string | null>(null)
  const compose = useMutation({
    mutationFn: () => post<Composed>(`/requests/${c.id}/compose-reply`, { text: notes.trim() }),
    onSuccess: (r) => {
      setDraft(r.body)
      if (r.note) toast.warning(r.note)
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const text = (draft ?? notes).trim()
  const send = () =>
    actions.provideInfo.mutate(text, {
      onSuccess: () => {
        setNotes('')
        setDraft(null)
      },
    })

  return (
    <Card className="border-l-4 border-l-accent">
      <CardHeader
        title="Reply to the operations team"
        icon={<Reply />}
        subtitle={hint ?? 'Answer their questions; your reply is added to the request.'}
      />
      <CardBody className="space-y-3">
        {draft === null ? (
          <>
            <Field
              label="Your answer — rough notes are fine"
              htmlFor="reply-notes"
              hint="“Write it with AI” turns your notes into a clear reply. It never adds facts."
            >
              <Textarea
                id="reply-notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="e.g. supplier is ShelfMart, original delivery was 6 Nov, 40 racks in stock"
              />
            </Field>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="primary"
                disabled={notes.trim().length < 2}
                loading={compose.isPending}
                onClick={() => compose.mutate()}
              >
                <Sparkles /> Write it with AI
              </Button>
              <Button
                disabled={notes.trim().length < 2}
                loading={actions.provideInfo.isPending}
                onClick={send}
              >
                <Send /> Send as written
              </Button>
            </div>
          </>
        ) : (
          <>
            <Field
              label="Your reply"
              htmlFor="reply-draft"
              hint="Drafted by AI from your notes — check it and edit anything before sending."
            >
              <Textarea
                id="reply-draft"
                className="min-h-48"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
              />
            </Field>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="primary"
                disabled={text.length < 2}
                loading={actions.provideInfo.isPending}
                onClick={send}
              >
                <Send /> Send reply
              </Button>
              <Button variant="ghost" onClick={() => setDraft(null)}>
                <ArrowLeft /> Back to my notes
              </Button>
            </div>
          </>
        )}
      </CardBody>
    </Card>
  )
}
