import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Field, Input, Select, Textarea } from '@/components/ui/form'
import type { CaseActions } from '@/hooks/useCaseActions'
import type { EventType } from '@/lib/types'

const EVENT_OPTIONS: { value: EventType; label: string }[] = [
  { value: 'supplier_date_revised', label: 'Supplier revised delivery date' },
  { value: 'launch_postponed', label: 'Launch / need postponed' },
  { value: 'inventory_updated', label: 'Inventory count updated' },
  { value: 'stakeholder_reply', label: 'Stakeholder replied' },
]

/** Edge cases 9 and 15: changing circumstances after the workflow started. */
export function EventDialog({
  open,
  onOpenChange,
  actions,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  actions: CaseActions
}) {
  const [type, setType] = useState<EventType>('supplier_date_revised')
  const [values, setValues] = useState<Record<string, string>>({})
  const val = (k: string) => values[k] ?? ''
  const set = (k: string) => (e: { target: { value: string } }) =>
    setValues((v) => ({ ...v, [k]: e.target.value }))

  const payload = (): Record<string, unknown> => {
    if (type === 'supplier_date_revised')
      return {
        ...(val('days') && { new_delay_days: Number(val('days')) }),
        ...(val('date') && { new_required_date: val('date') }),
      }
    if (type === 'inventory_updated')
      return { sku: val('sku'), location: val('location'), on_hand: Number(val('on_hand')) }
    if (type === 'stakeholder_reply') return { text: val('text') }
    return { reason: val('reason') }
  }
  const valid =
    type === 'supplier_date_revised'
      ? Boolean(val('days') || val('date'))
      : type === 'inventory_updated'
        ? Boolean(val('sku') && val('location') && val('on_hand'))
        : type === 'stakeholder_reply'
          ? val('text').trim().length > 0
          : true

  const submit = () =>
    actions.addEvent.mutate(
      { type, payload: payload() },
      {
        onSuccess: () => {
          setValues({})
          onOpenChange(false)
        },
      },
    )

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Report a change"
      description="The case is re-assessed; in-flight approvals are flagged for re-confirmation."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={!valid}
            loading={actions.addEvent.isPending}
            onClick={submit}
          >
            Record change
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="What changed?" htmlFor="event-type">
          <Select
            id="event-type"
            value={type}
            onChange={(e) => setType(e.target.value as EventType)}
          >
            {EVENT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </Select>
        </Field>
        {type === 'supplier_date_revised' && (
          <div className="grid grid-cols-2 gap-3">
            <Field label="New delay (days)" htmlFor="ev-days">
              <Input
                id="ev-days"
                type="number"
                min={0}
                value={val('days')}
                onChange={set('days')}
              />
            </Field>
            <Field label="New required date" htmlFor="ev-date" hint="e.g. 12 Nov">
              <Input id="ev-date" value={val('date')} onChange={set('date')} />
            </Field>
          </div>
        )}
        {type === 'inventory_updated' && (
          <div className="grid grid-cols-3 gap-3">
            <Field label="SKU" htmlFor="ev-sku">
              <Input id="ev-sku" placeholder="DU-500" value={val('sku')} onChange={set('sku')} />
            </Field>
            <Field label="Warehouse" htmlFor="ev-loc">
              <Input
                id="ev-loc"
                placeholder="Pune-WH"
                value={val('location')}
                onChange={set('location')}
              />
            </Field>
            <Field label="On hand" htmlFor="ev-qty">
              <Input
                id="ev-qty"
                type="number"
                min={0}
                value={val('on_hand')}
                onChange={set('on_hand')}
              />
            </Field>
          </div>
        )}
        {type === 'stakeholder_reply' && (
          <Field label="Reply text" htmlFor="ev-text">
            <Textarea id="ev-text" value={val('text')} onChange={set('text')} />
          </Field>
        )}
        {type === 'launch_postponed' && (
          <Field
            label="Details"
            htmlFor="ev-reason"
            hint="Without approved spend this cancels the case; with approved spend a manager must confirm."
          >
            <Input id="ev-reason" value={val('reason')} onChange={set('reason')} />
          </Field>
        )}
      </div>
    </Dialog>
  )
}
