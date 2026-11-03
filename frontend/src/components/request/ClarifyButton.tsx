import { Mail, MailCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { ButtonProps } from '@/components/ui/button'
import { useCaseNav } from '@/hooks/useCaseNav'
import type { CaseActions } from '@/hooks/useCaseActions'
import { clarifyQuestions, openClarification } from '@/lib/caseFlow'
import type { RequestDetail } from '@/lib/types'

/**
 * The one way to ask the requester for information. Drafts a single clarification covering every
 * open question; once a draft exists it becomes "Clarification drafted — view" and opens it, so
 * the same draft is never created twice.
 */
export function ClarifyButton({
  c,
  actions,
  variant = 'outline',
  onDone,
}: {
  c: RequestDetail
  actions: CaseActions
  variant?: ButtonProps['variant']
  onDone?: () => void
}) {
  const nav = useCaseNav()
  const existing = openClarification(c)
  const open = (id: string) => {
    onDone?.()
    nav?.openComm(id)
  }
  if (existing)
    return (
      <Button size="sm" variant={variant} onClick={() => open(existing.id)}>
        <MailCheck /> Clarification drafted — view
      </Button>
    )
  if (!c.allowed_actions.includes('request_info')) return null
  const n = clarifyQuestions(c).length
  return (
    <Button
      size="sm"
      variant={variant}
      loading={actions.generateComm.isPending}
      onClick={() => actions.generateComm.mutate('clarification', { onSuccess: (m) => open(m.id) })}
    >
      <Mail /> {n > 1 ? `Draft one clarification (${n} questions)` : 'Draft clarification'}
    </Button>
  )
}
