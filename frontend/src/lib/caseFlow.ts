import type { Communication, RequestDetail } from './types'

/** The case workflow, in the order of the assessment: intake → … → audit. */
export const STEPS = [
  { id: 'request', label: 'Request', hint: 'What came in' },
  { id: 'extraction', label: 'Extraction', hint: 'Facts & evidence' },
  { id: 'issues', label: 'Issues', hint: 'Missing & conflicting' },
  { id: 'risk', label: 'Risk', hint: 'Urgency & impact' },
  { id: 'decision', label: 'Actions', hint: 'Options, approval & messages' },
  { id: 'history', label: 'Tracking & audit', hint: 'Timeline & agents' },
] as const

export type StepId = (typeof STEPS)[number]['id']
export type StepState = 'done' | 'attention' | 'blocked' | 'idle'

// Shown as banners on the Request step instead of in the Issues list.
export const BANNER_ISSUE_TYPES = new Set(['injection', 'duplicate', 'circumstances_changed'])

const IN_FLIGHT = new Set(['pending', 'escalated'])

export function openIssues(c: RequestDetail) {
  return c.issues.filter((i) => i.status === 'open' && !BANNER_ISSUE_TYPES.has(i.type))
}

// Issue types the requester can answer; one clarification covers all of them (backend matches).
const CLARIFY_TYPES = new Set(['missing_info', 'ambiguity', 'conflict'])

/** Open questions for the requester (one per field), as covered by a single clarification. */
export function clarifyQuestions(c: RequestDetail) {
  const seen = new Set<string>()
  return openIssues(c).filter((i) => {
    if (!i.field || !CLARIFY_TYPES.has(i.type) || seen.has(i.field)) return false
    seen.add(i.field)
    return true
  })
}

/** The unsent clarification draft, if one exists — reused instead of drafting again. */
export function openClarification(c: RequestDetail): Communication | undefined {
  return c.communications.find(
    (m) => m.type === 'clarification' && (m.status === 'draft' || m.status === 'failed'),
  )
}

/** Extracted values a human flagged as incorrect (edge case 5). */
export function flaggedFields(c: RequestDetail) {
  return c.fields.filter((f) => f.flagged)
}

function draftCount(c: RequestDetail) {
  return c.communications.filter((m) => m.status === 'draft' || m.status === 'failed').length
}

function pendingApproval(c: RequestDetail) {
  return c.approvals.find((a) => IN_FLIGHT.has(a.status))
}

export interface StepStatus {
  state: StepState
  badge?: string
}

/** Per-step state for the step bar: what is finished, what needs a human, what is blocked. */
export function stepStatus(c: RequestDetail): Record<StepId, StepStatus> {
  const issues = openIssues(c)
  const blockers = issues.filter((i) => i.severity === 'blocker').length
  const drafts = draftCount(c)
  const can = (a: string) => c.allowed_actions.includes(a)
  const decisionNeeded = can('select_recommendation') || can('approve')
  const decided = c.approvals.some((a) => a.status === 'approved') || c.status === 'IN_PROGRESS'
  const disagreement = Boolean(c.risk.reconciled?.disagreement)
  const flagged = flaggedFields(c).length
  return {
    request: { state: c.injection.flag || c.duplicate_of ? 'attention' : 'done' },
    extraction: flagged
      ? { state: 'blocked', badge: `${flagged} flagged` }
      : c.missing_fields.length
        ? { state: 'attention', badge: `${c.missing_fields.length} missing` }
        : { state: 'done' },
    issues: issues.length
      ? { state: blockers ? 'blocked' : 'attention', badge: `${issues.length} open` }
      : { state: 'done' },
    risk: c.risk.reconciled
      ? { state: disagreement ? 'attention' : 'done', badge: c.risk.reconciled.risk_level }
      : { state: 'idle' },
    decision: decisionNeeded
      ? { state: 'attention', badge: can('approve') ? 'your decision' : 'choose option' }
      : drafts
        ? { state: 'attention', badge: `${drafts} draft to send` }
        : pendingApproval(c)
          ? { state: 'idle', badge: 'awaiting approval' }
          : { state: decided ? 'done' : 'idle' },
    history: { state: c.status === 'CLOSED' ? 'done' : 'idle' },
  }
}

export interface NextStep {
  step: StepId
  title: string
  detail?: string
}

/** One sentence telling the signed-in user what to do now, and where. */
export function nextStep(c: RequestDetail): NextStep {
  const can = (a: string) => c.allowed_actions.includes(a)
  const issues = openIssues(c)
  const pending = pendingApproval(c)
  const awaiting = pending
    ? (pending.assigned_to?.name ??
      (pending.approver_role === 'admin' ? 'the Director' : 'the Regional Manager'))
    : null

  switch (c.status) {
    case 'DUPLICATE':
      return { step: 'request', title: 'Linked as a duplicate — handled in the original case.' }
    case 'NEEDS_INFO':
      return {
        step: 'decision',
        title: 'Waiting for information from the requester.',
        detail: c.missing_fields.length
          ? `Missing: ${c.missing_fields.join(', ').replaceAll('_', ' ')}. Send the clarification under Actions, or add the information once they reply.`
          : 'Send the clarification under Actions, or add the information once they reply.',
      }
    case 'PENDING_REVIEW':
    case 'REJECTED':
      if (flaggedFields(c).length && can('correct_field'))
        return {
          step: 'extraction',
          title: `Correct ${flaggedFields(c).length} flagged value${flaggedFields(c).length > 1 ? 's' : ''}.`,
          detail: 'A flagged value blocks sending for approval until it is corrected or unflagged.',
        }
      if (issues.length && can('resolve_issue'))
        return {
          step: 'issues',
          title: `Review ${issues.length} open issue${issues.length > 1 ? 's' : ''} first.`,
          detail:
            'Resolve conflicts and ask for missing details before sending an option for approval.',
        }
      return can('select_recommendation')
        ? {
            step: 'decision',
            title:
              c.status === 'REJECTED'
                ? 'The option was rejected — choose an alternative.'
                : 'Choose an option and send it for approval.',
          }
        : { step: 'decision', title: 'The Operations Team is reviewing this case.' }
    case 'PENDING_APPROVAL':
    case 'ESCALATED':
      return can('approve')
        ? {
            step: 'decision',
            title: 'Your decision is needed.',
            detail: pending?.recommendation_title,
          }
        : { step: 'decision', title: `Waiting for ${awaiting ?? 'an approver'} to decide.` }
    case 'IN_PROGRESS':
    case 'APPROVED':
      return {
        step: 'decision',
        title: 'Approved — the action is in progress.',
        detail: 'Send the stakeholder update, then mark the case resolved when the work is done.',
      }
    case 'RESOLVED':
      return { step: 'decision', title: 'Resolved — send the closure note and close the case.' }
    case 'ON_HOLD':
      return { step: 'history', title: 'On hold — resume when the situation is clear.' }
    case 'CLOSED':
    case 'CANCELLED':
      return {
        step: 'history',
        title: c.status === 'CLOSED' ? 'Closed.' : 'Cancelled.',
        detail: 'The full audit trail is under Tracking & audit.',
      }
    default:
      return { step: 'request', title: 'The agents are analysing this request.' }
  }
}
