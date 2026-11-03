import { clarifyQuestions } from './caseFlow'
import { formatInr, titleCase } from './format'
import type { Recommendation, RequestDetail } from './types'

const MANAGER_LIMIT_INR = 50_000
const DAY_MS = 86_400_000

/** Who has to say yes, in plain words. */
export function approvalLabel(r: Recommendation): string {
  if (!r.requires_approval) return 'None — can start now'
  return r.estimated_cost_inr > MANAGER_LIMIT_INR
    ? 'Regional Manager → Director'
    : 'Regional Manager'
}

/** Whether the option is ready before the case deadline (only when the deadline is still ahead). */
export function timing(
  r: Recommendation,
  deadline: string | null,
  now: number = Date.now(),
): 'in time' | 'late' | null {
  if (!deadline) return null
  const left = new Date(deadline).getTime() - now
  if (left <= 0) return null
  return r.estimated_lead_time_days * DAY_MS <= left ? 'in time' : 'late'
}

/**
 * Suggested note from the Operations Team to the approving manager, built only from case data
 * (no LLM, so it cannot invent facts). The team edits it before sending.
 */
export function draftRoutingNote(
  c: RequestDetail,
  r: Recommendation,
  managerName?: string,
  now: number = Date.now(),
): string {
  const days = `${r.estimated_lead_time_days} day${r.estimated_lead_time_days === 1 ? '' : 's'}`
  const when = timing(r, c.deadline_at, now)
  const vsDeadline =
    when === 'in time' ? ' (before the deadline)' : when === 'late' ? ' (after the deadline)' : ''
  const open = clarifyQuestions(c).map((q) => titleCase(q.field ?? q.type).toLowerCase())
  const lines = [
    `Hi ${managerName?.split(' ')[0] ?? 'there'},`,
    '',
    `Please review ${c.ref} — ${c.subject} (${c.region}).`,
    `Recommended: ${r.title}.`,
    `${r.risk_reduction ? `${r.risk_reduction} ` : ''}Cost ${formatInr(r.estimated_cost_inr)}, ready in ${days}${vsDeadline}.`,
  ]
  if (r.rationale) lines.push(`Why: ${r.rationale}`)
  if (r.approval_reasons.length)
    lines.push(`Approval is needed because: ${r.approval_reasons.join('; ')}.`)
  if (r.estimated_cost_inr > MANAGER_LIMIT_INR)
    lines.push(
      `This is above your ${formatInr(MANAGER_LIMIT_INR)} limit — please forward it to the Director if you agree.`,
    )
  lines.push(
    open.length
      ? `Still open with the requester: ${open.join(', ')}.`
      : 'Operations Team check: extracted facts reviewed, no open questions.',
  )
  return lines.join('\n')
}
