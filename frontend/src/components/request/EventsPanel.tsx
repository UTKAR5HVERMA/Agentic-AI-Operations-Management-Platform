import { EmptyState } from '@/components/common/states'
import { formatIst, titleCase } from '@/lib/format'
import type { RequestDetail } from '@/lib/types'

export function EventsPanel({ c }: { c: RequestDetail }) {
  if (c.events.length === 0)
    return (
      <EmptyState
        title="No external changes"
        hint="Use “Report change” when a supplier revises dates or a launch moves."
      />
    )
  return (
    <ul className="space-y-2">
      {c.events.map((e) => (
        <li key={e.id} className="border-l-4 border-info bg-white px-4 py-3 ring-1 ring-line">
          <p className="font-bold">{titleCase(e.type)}</p>
          {(e.diff.changes ?? []).map((ch) => (
            <p key={ch.field} className="text-sm">
              {titleCase(ch.field)}: <s className="text-ink-muted">{String(ch.old ?? '—')}</s> →{' '}
              <b>{String(ch.new ?? '—')}</b>
            </p>
          ))}
          <p className="text-xs text-ink-muted">
            {e.created_by} · {formatIst(e.created_at)}
          </p>
        </li>
      ))}
    </ul>
  )
}
