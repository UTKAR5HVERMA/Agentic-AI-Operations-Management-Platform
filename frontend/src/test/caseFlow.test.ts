import { describe, expect, it } from 'vitest'
import { clarifyQuestions, nextStep, openClarification, stepStatus } from '@/lib/caseFlow'
import type { RequestDetail } from '@/lib/types'

function makeCase(over: Partial<RequestDetail> = {}): RequestDetail {
  const base = {
    status: 'PENDING_REVIEW',
    allowed_actions: ['resolve_issue', 'select_recommendation', 'request_info', 'correct_field'],
    issues: [],
    missing_fields: [],
    fields: [],
    approvals: [],
    communications: [],
    injection: { flag: false, patterns: [], quarantined_spans: [] },
    duplicate_of: null,
    risk: { ops: null, financial: null, reconciled: null },
  }
  return { ...base, ...over } as unknown as RequestDetail
}

const issue = (severity: string, type = 'missing_info') => ({
  id: severity + type,
  type,
  severity,
  field: 'supplier',
  message: 'Missing supplier.',
  details: {},
  status: 'open',
  resolution_note: null,
  created_at: '',
})

describe('nextStep', () => {
  it('sends the Operations Team to open issues before the decision', () => {
    const c = makeCase({ issues: [issue('warning')] as RequestDetail['issues'] })
    expect(nextStep(c)).toMatchObject({ step: 'issues', title: 'Review 1 open issue first.' })
  })

  it('asks for a choice once issues are clear', () => {
    expect(nextStep(makeCase()).step).toBe('decision')
  })

  it('tells a manager their decision is needed, and others who it waits for', () => {
    const approvals = [
      { status: 'pending', approver_role: 'ops_manager', assigned_to: { id: '1', name: 'Priya' } },
    ] as unknown as RequestDetail['approvals']
    const manager = makeCase({
      status: 'PENDING_APPROVAL',
      approvals,
      allowed_actions: ['approve'],
    })
    expect(nextStep(manager).title).toBe('Your decision is needed.')
    const team = makeCase({ status: 'PENDING_APPROVAL', approvals, allowed_actions: [] })
    expect(nextStep(team).title).toBe('Waiting for Priya to decide.')
  })

  it('ignores banner-only issues such as injection', () => {
    const c = makeCase({ issues: [issue('warning', 'injection')] as RequestDetail['issues'] })
    expect(nextStep(c).step).toBe('decision')
  })
})

describe('stepStatus', () => {
  it('marks blockers red and counts open issues', () => {
    const c = makeCase({
      issues: [issue('blocker'), issue('warning', 'ambiguity')] as RequestDetail['issues'],
    })
    expect(stepStatus(c).issues).toEqual({ state: 'blocked', badge: '2 open' })
    expect(stepStatus(c).decision.state).toBe('attention')
  })
})

describe('clarification', () => {
  it('groups open questions by field into one clarification', () => {
    const issues = [
      issue('warning'),
      { ...issue('warning', 'conflict'), id: 'c', field: 'quantity_available' },
      { ...issue('blocker'), id: 'dup' }, // same field as the first: asked once
      issue('warning', 'agent_disagreement'), // not a question for the requester
    ] as RequestDetail['issues']
    expect(clarifyQuestions(makeCase({ issues })).map((i) => i.field)).toEqual([
      'supplier',
      'quantity_available',
    ])
  })

  it('reuses an unsent draft instead of creating another', () => {
    const communications = [
      { id: 'sent', type: 'clarification', status: 'sent' },
      { id: 'draft', type: 'clarification', status: 'draft' },
    ] as unknown as RequestDetail['communications']
    expect(openClarification(makeCase({ communications }))?.id).toBe('draft')
  })

  it('points a case waiting for information at the Actions step', () => {
    expect(nextStep(makeCase({ status: 'NEEDS_INFO' })).step).toBe('decision')
  })
})

describe('flagged extraction', () => {
  it('blocks the Extraction step and sends the team there first', () => {
    const fields = [{ field: 'quantity_required', flagged: true }] as RequestDetail['fields']
    const c = makeCase({ fields, issues: [issue('warning')] as RequestDetail['issues'] })
    expect(stepStatus(c).extraction).toEqual({ state: 'blocked', badge: '1 flagged' })
    expect(nextStep(c)).toMatchObject({ step: 'extraction', title: 'Correct 1 flagged value.' })
  })
})
