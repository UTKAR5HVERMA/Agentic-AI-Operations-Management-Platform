import { FileSearch, Flag, Plus } from 'lucide-react'
import { useState } from 'react'
import { SourceBadge } from '@/components/common/badges'
import { ConfidenceMeter } from '@/components/common/ConfidenceMeter'
import { MIN_REASON } from '@/components/common/ReasonDialog'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/card'
import { Input } from '@/components/ui/form'
import { Table, Td, Th, Tr } from '@/components/ui/table'
import type { CaseActions } from '@/hooks/useCaseActions'
import { FIELD_LABEL } from '@/lib/labels'
import type { ExtractedField, RequestDetail } from '@/lib/types'
import { cn } from '@/lib/utils'
import { FieldFlagActions } from './FieldFlagActions'

interface Props {
  c: RequestDetail
  actions: CaseActions
  onHighlight: (evidence: string | null) => void
}

function EditRow({
  name,
  initial,
  actions,
  onDone,
}: {
  name: string
  initial: string
  actions: CaseActions
  onDone: () => void
}) {
  const [value, setValue] = useState(initial)
  const [reason, setReason] = useState('')
  const valid = value.trim() && reason.trim().length >= MIN_REASON
  return (
    <Tr className="bg-accent/10">
      <Td className="font-bold">{FIELD_LABEL[name] ?? name}</Td>
      <Td colSpan={4}>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            aria-label="New value"
            className="w-48"
            autoFocus
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
          <Input
            aria-label="Reason"
            className="min-w-56 flex-1"
            placeholder={`Reason (≥ ${MIN_REASON} chars, audited)`}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <Button
            size="sm"
            variant="primary"
            disabled={!valid}
            loading={actions.correctField.isPending}
            onClick={() =>
              actions.correctField.mutate(
                { field: name, value: value.trim(), reason: reason.trim() },
                { onSuccess: onDone },
              )
            }
          >
            Save & re-run
          </Button>
          <Button size="sm" variant="ghost" onClick={onDone}>
            Cancel
          </Button>
        </div>
      </Td>
    </Tr>
  )
}

function ValueCell({ f }: { f: ExtractedField }) {
  const previous = f.history[0]
  return (
    <div>
      <span className="line-clamp-3 font-bold" title={f.value ?? undefined}>
        {f.value}
      </span>
      {f.corrected_by && (
        <p className="mt-0.5 text-xs text-ink-muted">
          Corrected by {f.corrected_by}
          {previous && (
            <>
              {' '}
              · was <s>{previous.value}</s>
            </>
          )}
        </p>
      )}
      {f.flagged && (
        <p className="mt-1 flex items-start gap-1 text-xs font-bold text-bad">
          <Flag className="mt-0.5 size-3 shrink-0" />
          <span>
            Flagged as incorrect
            {f.flag_reason && <span className="font-normal">: {f.flag_reason}</span>}
          </span>
        </p>
      )}
      {f.source === 'event' && previous && (
        <p className="mt-0.5 text-xs text-info">
          Updated by event · was <s>{previous.value}</s>
        </p>
      )}
    </div>
  )
}

export function ExtractedFields({ c, actions, onHighlight }: Props) {
  const [editing, setEditing] = useState<string | null>(null)
  const canEdit = c.allowed_actions.includes('correct_field')
  const order = Object.keys(FIELD_LABEL)
  const fields = [...c.fields].sort((a, b) => order.indexOf(a.field) - order.indexOf(b.field))

  return (
    <Card>
      <CardHeader
        title="Extracted information"
        icon={<FileSearch />}
        subtitle="Every value quotes its evidence from the email (hover to locate it). Wrong value? Flag it, then correct it."
      />
      <Table>
        <thead>
          <tr>
            <Th>Field</Th>
            <Th>Value</Th>
            <Th>Evidence</Th>
            <Th>Confidence · source</Th>
            <Th className="w-36">Review</Th>
          </tr>
        </thead>
        <tbody>
          {fields.map((f) =>
            editing === f.field ? (
              <EditRow
                key={f.field}
                name={f.field}
                initial={f.value ?? ''}
                actions={actions}
                onDone={() => setEditing(null)}
              />
            ) : (
              <Tr key={f.field} className={cn(f.flagged && 'bg-bad/5')}>
                <Td className="font-bold whitespace-nowrap">{FIELD_LABEL[f.field] ?? f.field}</Td>
                <Td className="max-w-56">
                  <ValueCell f={f} />
                </Td>
                <Td className="max-w-56">
                  {f.evidence ? (
                    <q
                      className="line-clamp-3 cursor-help text-xs text-ink-muted italic hover:bg-accent/40"
                      onMouseEnter={() => onHighlight(f.evidence)}
                      onMouseLeave={() => onHighlight(null)}
                    >
                      {f.evidence}
                    </q>
                  ) : (
                    <span className="text-xs text-ink-muted">—</span>
                  )}
                </Td>
                <Td className="w-36">
                  <ConfidenceMeter value={f.confidence} compact className="min-w-0" />
                  <div className="mt-1.5">
                    <SourceBadge source={f.source} />
                  </div>
                </Td>
                <Td className="px-2">
                  <FieldFlagActions
                    c={c}
                    f={f}
                    actions={actions}
                    onCorrect={() => setEditing(f.field)}
                  />
                </Td>
              </Tr>
            ),
          )}
          {c.missing_fields.map((name) =>
            editing === name ? (
              <EditRow
                key={name}
                name={name}
                initial=""
                actions={actions}
                onDone={() => setEditing(null)}
              />
            ) : (
              <Tr key={name} className="bg-bad/5">
                <Td className="font-bold">{FIELD_LABEL[name] ?? name}</Td>
                <Td colSpan={2} className="font-bold text-bad">
                  Not found in the request
                </Td>
                <Td colSpan={2}>
                  {canEdit && (
                    <Button size="sm" onClick={() => setEditing(name)}>
                      <Plus /> Add
                    </Button>
                  )}
                </Td>
              </Tr>
            ),
          )}
        </tbody>
      </Table>
    </Card>
  )
}
