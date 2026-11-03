import { describe, expect, it } from 'vitest'
import { approvalLabel, draftRoutingNote, timing } from '@/lib/recommendation'
import type { Recommendation, RequestDetail } from '@/lib/types'

const rec = (over: Partial<Recommendation>) =>
  ({
    requires_approval: true,
    estimated_cost_inr: 0,
    estimated_lead_time_days: 2,
    ...over,
  }) as Recommendation

describe('approvalLabel', () => {
  it('says who has to approve, in plain words', () => {
    expect(approvalLabel(rec({ requires_approval: false }))).toBe('None — can start now')
    expect(approvalLabel(rec({ estimated_cost_inr: 42_000 }))).toBe('Regional Manager')
    expect(approvalLabel(rec({ estimated_cost_inr: 147_000 }))).toBe('Regional Manager → Director')
  })
})

describe('timing', () => {
  const now = Date.parse('2026-11-03T10:00:00Z')
  it('compares lead time with the deadline', () => {
    expect(timing(rec({}), '2026-11-06T10:00:00Z', now)).toBe('in time')
    expect(timing(rec({ estimated_lead_time_days: 5 }), '2026-11-06T10:00:00Z', now)).toBe('late')
  })
  it('says nothing when there is no deadline or it has passed', () => {
    expect(timing(rec({}), null, now)).toBeNull()
    expect(timing(rec({}), '2026-11-02T10:00:00Z', now)).toBeNull()
  })
})

describe('draftRoutingNote', () => {
  const now = Date.parse('2026-11-03T10:00:00Z')
  const c = {
    ref: 'OPS-2026-0007',
    subject: 'Urgent Delivery Delay',
    region: 'West',
    deadline_at: '2026-11-08T10:00:00Z',
    issues: [],
  } as unknown as RequestDetail

  it('summarises the option for the chosen manager from case data only', () => {
    const note = draftRoutingNote(
      c,
      rec({
        title: 'Transfer 120 units from Pune-WH',
        risk_reduction: 'Covers 100% of the 120-unit shortfall.',
        estimated_cost_inr: 12_000,
        rationale: 'Uses existing stock.',
        approval_reasons: ['Risk is critical'],
      }),
      'Priya Manager',
      now,
    )
    expect(note).toContain('Hi Priya,')
    expect(note).toContain('Recommended: Transfer 120 units from Pune-WH.')
    expect(note).toContain('Cost ₹12,000, ready in 2 days (before the deadline).')
    expect(note).toContain('Approval is needed because: Risk is critical.')
    expect(note).toContain('no open questions')
    expect(note).not.toContain('Director')
  })

  it('asks the manager to forward spend above their limit', () => {
    const note = draftRoutingNote(c, rec({ estimated_cost_inr: 147_000, approval_reasons: [] }))
    expect(note).toContain('please forward it to the Director')
  })
})
