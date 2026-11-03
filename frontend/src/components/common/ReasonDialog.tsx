import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Field, Textarea } from '@/components/ui/form'

export const MIN_REASON = 5

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  confirmLabel: string
  destructive?: boolean
  pending?: boolean
  label?: string
  /** Minimum length; defaults to MIN_REASON. */
  minLength?: number
  onConfirm: (reason: string) => void
}

/** Every destructive or overriding action asks "why" (FRONTEND.md §6). Reason ≥ 5 chars. */
export function ReasonDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  destructive,
  pending,
  label = 'Reason (recorded in the audit trail)',
  minLength = MIN_REASON,
  onConfirm,
}: Props) {
  const [reason, setReason] = useState('')
  const [touched, setTouched] = useState(false)
  const valid = reason.trim().length >= minLength

  const close = (next: boolean) => {
    if (!next) {
      setReason('')
      setTouched(false)
    }
    onOpenChange(next)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={close}
      title={title}
      description={description}
      footer={
        <>
          <Button variant="ghost" onClick={() => close(false)}>
            Cancel
          </Button>
          <Button
            variant={destructive ? 'danger' : 'primary'}
            loading={pending}
            disabled={!valid}
            onClick={() => onConfirm(reason.trim())}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <Field
        label={label}
        htmlFor="reason"
        error={
          touched && !valid
            ? `Please give a reason of at least ${minLength} characters.`
            : undefined
        }
      >
        <Textarea
          id="reason"
          autoFocus
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          onBlur={() => setTouched(true)}
          placeholder="Why are you doing this?"
        />
      </Field>
    </Dialog>
  )
}
