import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Field, Input, Select, Textarea } from '@/components/ui/form'
import { useApprovers } from '@/hooks/queries'
import type { CaseActions } from '@/hooks/useCaseActions'

const schema = z.object({
  title: z.string().trim().min(3, 'At least 3 characters').max(200),
  description: z.string().trim().min(3, 'Describe the action').max(2000),
  estimated_cost_inr: z.coerce.number().int().min(0, 'Cost cannot be negative'),
  estimated_lead_time_days: z.coerce.number().min(0).max(365),
  reason: z.string().trim().min(5, 'Explain why you are overriding (≥ 5 characters)'),
})
type Values = z.infer<typeof schema>

/** R7: a human replaces the AI options; the reason is recorded and approval policy still applies. */
export function OverrideDialog({
  open,
  onOpenChange,
  actions,
  region,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  actions: CaseActions
  region: string
}) {
  const approvers = useApprovers()
  const [chosen, setChosen] = useState('')
  const approverId =
    chosen || (approvers.data?.find((m) => m.region === region) ?? approvers.data?.[0])?.id || ''
  const form = useForm<z.input<typeof schema>, unknown, Values>({
    resolver: zodResolver(schema),
    defaultValues: { estimated_cost_inr: 0, estimated_lead_time_days: 0 },
  })
  const e = form.formState.errors
  const submit = form.handleSubmit((v) =>
    actions.override.mutate(
      { ...v, approver_id: approverId || undefined },
      {
        onSuccess: () => {
          form.reset()
          onOpenChange(false)
        },
      },
    ),
  )
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Override with my own action"
      description="Replaces the AI options. Approval policy still applies to the amount you enter."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" loading={actions.override.isPending} onClick={submit}>
            Submit override
          </Button>
        </>
      }
    >
      <form className="space-y-4" onSubmit={submit} noValidate>
        <Field label="Action title" htmlFor="ov-title" error={e.title?.message}>
          <Input id="ov-title" {...form.register('title')} />
        </Field>
        <Field label="Description" htmlFor="ov-desc" error={e.description?.message}>
          <Textarea id="ov-desc" {...form.register('description')} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Estimated cost (₹)" htmlFor="ov-cost" error={e.estimated_cost_inr?.message}>
            <Input id="ov-cost" type="number" min={0} {...form.register('estimated_cost_inr')} />
          </Field>
          <Field
            label="Lead time (days)"
            htmlFor="ov-lead"
            error={e.estimated_lead_time_days?.message}
          >
            <Input
              id="ov-lead"
              type="number"
              min={0}
              step="0.5"
              {...form.register('estimated_lead_time_days')}
            />
          </Field>
        </div>
        <Field label="Regional Manager who decides (if approval is needed)" htmlFor="ov-approver">
          <Select
            id="ov-approver"
            value={approverId}
            onChange={(ev) => setChosen(ev.target.value)}
            disabled={!approvers.data}
          >
            {approvers.data?.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} · {m.region}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Why override the AI? (audited)" htmlFor="ov-reason" error={e.reason?.message}>
          <Textarea id="ov-reason" {...form.register('reason')} />
        </Field>
      </form>
    </Dialog>
  )
}
