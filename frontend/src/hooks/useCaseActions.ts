import { toast } from 'sonner'
import { del, patch, post } from '@/lib/api'
import type { Approval, CommType, Communication, EventType, RequestDetail } from '@/lib/types'
import { useCaseAction } from './queries'

/** All case-level mutations (BACKEND.md §8). Each sends `version` for optimistic locking. */
export function useCaseActions(c: RequestDetail) {
  const base = `/requests/${c.id}`
  const v = { version: c.version }

  return {
    correctField: useCaseAction(
      (b: { field: string; value: string; reason: string }) =>
        patch<RequestDetail>(`${base}/fields`, { ...b, ...v }),
      'Field corrected — downstream agents re-ran',
    ),
    flagField: useCaseAction(
      (b: { field: string; reason: string }) =>
        post<RequestDetail>(`${base}/fields/flag`, { ...b, ...v }),
      'Flagged as incorrect — correct the value next',
    ),
    reanalyze: useCaseAction(
      () => post<RequestDetail>(`${base}/reanalyze`, v),
      'Re-analysis complete',
    ),
    provideInfo: useCaseAction(
      (text: string) => post<RequestDetail>(`${base}/provide-info`, { text, ...v }),
      'Information added and case re-analysed',
    ),
    resolveIssue: useCaseAction(
      (b: { issueId: string; resolution: string; value?: string; note: string }) =>
        post<RequestDetail>(`${base}/issues/${b.issueId}/resolve`, {
          resolution: b.resolution,
          value: b.value,
          note: b.note,
          ...v,
        }),
      'Issue updated',
    ),
    select: useCaseAction(
      (b: { recId: string; note?: string; approverId?: string }) =>
        post<RequestDetail>(`${base}/recommendations/${b.recId}/select`, {
          note: b.note,
          approver_id: b.approverId,
          ...v,
        }),
      (r) =>
        r.status === 'PENDING_APPROVAL'
          ? 'Sent for approval'
          : 'Action started — no approval needed',
    ),
    override: useCaseAction(
      (b: {
        title: string
        description: string
        estimated_cost_inr: number
        estimated_lead_time_days: number
        reason: string
        approver_id?: string
      }) => post<RequestDetail>(`${base}/override`, { ...b, ...v }),
      'Your option replaced the AI recommendation',
    ),
    markDuplicate: useCaseAction(
      (masterId: string) => post<RequestDetail>(`${base}/duplicate`, { master_id: masterId, ...v }),
      'Merged into the existing case',
    ),
    notDuplicate: useCaseAction(
      () => post<RequestDetail>(`${base}/not-duplicate`, v),
      'Marked as not a duplicate',
    ),
    transition: useCaseAction(
      (b: { to: string; reason?: string }) =>
        post<RequestDetail>(`${base}/transition`, { ...b, ...v }),
      'Status updated',
    ),
    cancel: useCaseAction(
      (reason: string) => post<RequestDetail>(`${base}/cancel`, { reason, ...v }),
      'Request cancelled',
    ),
    addEvent: useCaseAction(
      (b: { type: EventType; payload: Record<string, unknown> }) =>
        post<RequestDetail>(`${base}/events`, { ...b, ...v }),
      'Change recorded — case re-assessed',
    ),
    generateComm: useCaseAction(
      (type: CommType) => post<Communication>(`${base}/communications/generate`, { type }),
      'Draft ready',
    ),
    discardComm: useCaseAction((id: string) => del(`/communications/${id}`), 'Draft deleted'),
    updateComm: useCaseAction(
      (b: { id: string; subject: string; body: string; to: string[] }) =>
        patch<Communication>(`/communications/${b.id}`, {
          subject: b.subject,
          body: b.body,
          to: b.to,
        }),
      'Draft saved',
    ),
    // A failed delivery is a 200 with status "failed", so it gets an error toast, not a success one.
    sendComm: useCaseAction(async (id: string) => {
      const m = await post<Communication>(`/communications/${id}/send`)
      if (m.status === 'sent') toast.success('Sent')
      else
        toast.error(`Not delivered: ${m.last_error ?? 'unknown error'}`, {
          description:
            m.delivered_via === 'in_app'
              ? 'Posted in-app instead. The case has an open communication-failure issue.'
              : `Retrying automatically (${m.attempts}/3). The case is flagged until it is delivered.`,
          duration: 8000,
        })
      return m
    }),
  }
}

export type CaseActions = ReturnType<typeof useCaseActions>

export function useApprovalActions() {
  return {
    approve: useCaseAction(
      (b: { id: string; note?: string; reconfirm?: boolean; selfOverride?: boolean }) =>
        post<Approval>(`/approvals/${b.id}/approve`, {
          note: b.note,
          reconfirm: b.reconfirm ?? false,
          self_override: b.selfOverride ?? false,
        }),
      (a) => (a.self_approved ? 'Self-approved — flagged for review' : 'Approved'),
    ),
    reject: useCaseAction(
      (b: { id: string; note: string }) =>
        post<Approval>(`/approvals/${b.id}/reject`, { note: b.note }),
      'Rejected — alternatives re-proposed',
    ),
    escalate: useCaseAction(
      (b: { id: string; note: string }) =>
        post<Approval>(`/approvals/${b.id}/escalate`, { note: b.note }),
      'Forwarded to the Director',
    ),
  }
}
