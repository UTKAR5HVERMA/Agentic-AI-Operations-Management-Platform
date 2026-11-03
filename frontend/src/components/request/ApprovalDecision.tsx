import { ArrowUpCircle, Check, RotateCcw, ShieldAlert, X } from 'lucide-react'
import { useState } from 'react'
import { ReasonDialog } from '@/components/common/ReasonDialog'
import { Button } from '@/components/ui/button'
import { useApprovalActions } from '@/hooks/useCaseActions'
import { useAuth } from '@/lib/auth'
import { APPROVER_ROLES } from '@/lib/roles'
import type { Approval } from '@/lib/types'

const IN_FLIGHT = new Set(['pending', 'escalated'])

/**
 * Approve / Reject / Forward to Director. Approver-type roles always see the buttons; the server
 * decides and a 403 explains why (e.g. "You can approve up to ₹50,000. Forward it to the
 * Director.") — edge case 11.
 */
export function ApprovalDecision({ a }: { a: Approval }) {
  const { hasRole } = useAuth()
  const { approve, reject, escalate } = useApprovalActions()
  const [dialog, setDialog] = useState<null | 'reject' | 'forward' | 'override'>(null)
  if (!IN_FLIGHT.has(a.status) || !hasRole(...APPROVER_ROLES)) return null
  const managerDecision = a.approver_role === 'ops_manager'

  return (
    <div className="flex flex-wrap gap-2">
      {a.needs_self_override ? (
        <Button size="sm" variant="primary" onClick={() => setDialog('override')}>
          <ShieldAlert /> Approve my own request…
        </Button>
      ) : (
        <Button
          size="sm"
          variant="primary"
          loading={approve.isPending}
          onClick={() => approve.mutate({ id: a.id, reconfirm: a.stale })}
        >
          {a.stale ? <RotateCcw /> : <Check />} {a.stale ? 'Re-confirm & approve' : 'Approve'}
        </Button>
      )}
      <Button size="sm" variant="danger" onClick={() => setDialog('reject')}>
        <X /> Reject
      </Button>
      {managerDecision && (
        <Button size="sm" variant="ghost" onClick={() => setDialog('forward')}>
          <ArrowUpCircle /> Forward to Director
        </Button>
      )}
      <ReasonDialog
        open={dialog === 'reject'}
        onOpenChange={(o) => !o && setDialog(null)}
        title="Reject this action"
        description={`${a.recommendation_title}. The agents will re-propose alternatives without it.`}
        confirmLabel="Reject"
        destructive
        pending={reject.isPending}
        onConfirm={(note) =>
          reject.mutate({ id: a.id, note }, { onSuccess: () => setDialog(null) })
        }
      />
      <ReasonDialog
        open={dialog === 'override'}
        onOpenChange={(o) => !o && setDialog(null)}
        title="Approve your own request"
        description="You raised this request and nobody is above the Director. You can approve it, but it is marked “Self-approved by Director”, recorded in the audit trail and listed in the management summary for review."
        label="Justification (why you are approving your own request)"
        minLength={15}
        confirmLabel="Self-approve"
        pending={approve.isPending}
        onConfirm={(note) =>
          approve.mutate(
            { id: a.id, note, reconfirm: a.stale, selfOverride: true },
            { onSuccess: () => setDialog(null) },
          )
        }
      />
      <ReasonDialog
        open={dialog === 'forward'}
        onOpenChange={(o) => !o && setDialog(null)}
        title="Forward to the Director"
        description="The Director makes the final decision. Your note is sent with the request."
        label="Why the Director should decide (recorded in the audit trail)"
        confirmLabel="Forward"
        pending={escalate.isPending}
        onConfirm={(note) =>
          escalate.mutate({ id: a.id, note }, { onSuccess: () => setDialog(null) })
        }
      />
    </div>
  )
}
