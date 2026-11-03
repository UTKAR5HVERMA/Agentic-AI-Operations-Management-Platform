import { Flag, FlagOff, Pencil } from 'lucide-react'
import { useState } from 'react'
import { ReasonDialog } from '@/components/common/ReasonDialog'
import { Button } from '@/components/ui/button'
import type { CaseActions } from '@/hooks/useCaseActions'
import { FIELD_LABEL } from '@/lib/labels'
import type { ExtractedField, RequestDetail } from '@/lib/types'

/**
 * Edge case 5 (incorrect AI extraction) in two steps: flag the value as wrong, then correct it.
 * An AI value has no direct edit button; a value a human already set can be edited again.
 */
export function FieldFlagActions({
  c,
  f,
  actions,
  onCorrect,
}: {
  c: RequestDetail
  f: ExtractedField
  actions: CaseActions
  onCorrect: () => void
}) {
  const [dialog, setDialog] = useState<null | 'flag' | 'unflag'>(null)
  const can = (a: string) => c.allowed_actions.includes(a)
  const label = (FIELD_LABEL[f.field] ?? f.field).toLowerCase()
  const flagIssue = c.issues.find(
    (i) => i.type === 'extraction_flagged' && i.field === f.field && i.status === 'open',
  )

  if (!can('correct_field')) return null
  if (f.source === 'human')
    return (
      <Button size="sm" variant="ghost" aria-label={`Edit ${label}`} onClick={onCorrect}>
        <Pencil /> Edit
      </Button>
    )

  return (
    <div className="flex flex-col items-start gap-1">
      {f.flagged ? (
        <>
          <Button size="sm" variant="primary" onClick={onCorrect}>
            <Pencil /> Correct value
          </Button>
          {flagIssue && can('resolve_issue') && (
            <Button size="sm" variant="ghost" onClick={() => setDialog('unflag')}>
              <FlagOff /> Remove flag
            </Button>
          )}
        </>
      ) : (
        can('flag_field') && (
          <Button
            size="sm"
            variant="ghost"
            aria-label={`Flag ${label} as incorrect`}
            title="The AI got this wrong? Flag it, then correct it."
            onClick={() => setDialog('flag')}
          >
            <Flag /> Flag
          </Button>
        )
      )}
      <ReasonDialog
        open={dialog === 'flag'}
        onOpenChange={(o) => !o && setDialog(null)}
        title={`Flag the ${label} as incorrect`}
        description={`The AI extracted "${f.value}". The case can't be sent for approval until you correct it or remove the flag.`}
        label="What is wrong with it? (recorded in the audit trail)"
        confirmLabel="Flag as incorrect"
        destructive
        pending={actions.flagField.isPending}
        onConfirm={(reason) =>
          actions.flagField.mutate({ field: f.field, reason }, { onSuccess: () => setDialog(null) })
        }
      />
      <ReasonDialog
        open={dialog === 'unflag'}
        onOpenChange={(o) => !o && setDialog(null)}
        title="Remove the flag"
        description={`Keep "${f.value}" as extracted by the AI.`}
        label="Why is the value right after all?"
        confirmLabel="Remove flag"
        pending={actions.resolveIssue.isPending}
        onConfirm={(note) =>
          flagIssue &&
          actions.resolveIssue.mutate(
            { issueId: flagIssue.id, resolution: 'dismiss', note },
            { onSuccess: () => setDialog(null) },
          )
        }
      />
    </div>
  )
}
