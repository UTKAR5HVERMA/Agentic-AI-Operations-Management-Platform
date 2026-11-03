import { MessageCircleQuestion } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import type { CaseActions } from '@/hooks/useCaseActions'
import { clarifyQuestions, openClarification } from '@/lib/caseFlow'
import { titleCase } from '@/lib/format'
import type { RequestDetail } from '@/lib/types'
import { ClarifyButton } from './ClarifyButton'

/**
 * Communication as a recommended action: when the request has open questions, asking the
 * requester (one combined message) is offered alongside the costed options.
 */
export function ClarifyActionCard({ c, actions }: { c: RequestDetail; actions: CaseActions }) {
  const questions = clarifyQuestions(c)
  const draft = openClarification(c)
  const sent = c.communications.find((m) => m.type === 'clarification' && m.status === 'sent')
  if (!questions.length && !draft) return null

  return (
    <article className="border border-l-4 border-line border-l-info bg-white">
      <div className="flex items-start gap-3 px-4 pt-3">
        <span className="flex size-7 shrink-0 items-center justify-center bg-page">
          <MessageCircleQuestion className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[15px]">Ask the requester for the missing details</h3>
            <Badge tone="info">Communication</Badge>
            {draft && <Badge tone="neutral">Drafted</Badge>}
            {sent && !draft && <Badge tone="ok">Sent · awaiting reply</Badge>}
          </div>
          <p className="mt-1 text-sm text-ink-muted">
            One message to {c.sender.name ?? c.sender.email ?? 'the requester'} covering every open
            question. No cost; do this before sending an option for approval if the answer could
            change the decision.
          </p>
        </div>
      </div>
      {questions.length > 0 && (
        <ul className="mx-4 mt-3 space-y-1 bg-page px-3 py-2 text-sm">
          {questions.map((q) => (
            <li key={q.id} className="flex gap-2">
              <Badge tone="neutral" className="shrink-0">
                {titleCase(q.type)}
              </Badge>
              <span>{q.message}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="px-4 py-3">
        <ClarifyButton c={c} actions={actions} variant="primary" />
      </div>
    </article>
  )
}
