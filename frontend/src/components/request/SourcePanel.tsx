import { Mail } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Card, CardHeader } from '@/components/ui/card'
import type { RequestDetail } from '@/lib/types'
import { cn } from '@/lib/utils'

type Kind = 'evidence' | 'active' | 'quarantine'
interface Range {
  start: number
  end: number
  kind: Kind
}

const KIND_RANK: Record<Kind, number> = { quarantine: 3, active: 2, evidence: 1 }

function findAll(text: string, needle: string, kind: Kind): Range[] {
  const out: Range[] = []
  const hay = text.toLowerCase()
  const n = needle.toLowerCase().trim()
  if (n.length < 2) return out
  for (let i = hay.indexOf(n); i !== -1; i = hay.indexOf(n, i + n.length))
    out.push({ start: i, end: i + n.length, kind })
  return out
}

/** Split text into plain/marked segments; higher-ranked kinds win where ranges overlap. */
function highlight(text: string, ranges: Range[]): ReactNode[] {
  const marks: (Kind | null)[] = new Array(text.length).fill(null)
  for (const r of ranges)
    for (let i = r.start; i < Math.min(r.end, text.length); i++)
      if (!marks[i] || KIND_RANK[r.kind] > KIND_RANK[marks[i] as Kind]) marks[i] = r.kind
  const out: ReactNode[] = []
  let i = 0
  while (i < text.length) {
    const kind = marks[i]
    let j = i
    while (j < text.length && marks[j] === kind) j++
    const chunk = text.slice(i, j)
    out.push(
      kind === null ? (
        chunk
      ) : (
        <mark
          key={i}
          title={
            kind === 'quarantine'
              ? 'Quarantined — not used by the AI'
              : 'Evidence for an extracted field'
          }
          className={cn(
            kind === 'quarantine' && 'bg-bad/15 text-bad line-through',
            kind === 'evidence' && 'bg-accent/45 text-ink',
            kind === 'active' && 'bg-accent text-ink ring-2 ring-ink',
          )}
        >
          {chunk}
        </mark>
      ),
    )
    i = j
  }
  return out
}

export function SourcePanel({ c, active }: { c: RequestDetail; active: string | null }) {
  const [view, setView] = useState<'raw' | 'sanitized'>('raw')
  const text = view === 'raw' ? c.raw_text : c.sanitized_text
  const content = useMemo(() => {
    const ranges: Range[] = c.fields.flatMap((f) =>
      f.evidence ? findAll(text, f.evidence, 'evidence') : [],
    )
    if (active) ranges.push(...findAll(text, active, 'active'))
    if (view === 'raw')
      for (const s of c.injection.quarantined_spans ?? [])
        ranges.push(...findAll(text, s.text, 'quarantine'))
    return highlight(text, ranges)
  }, [c, text, active, view])

  return (
    <Card>
      <CardHeader
        title="Source"
        icon={<Mail />}
        subtitle={`${c.sender.name ?? ''} ${c.sender.email ? `<${c.sender.email}>` : ''}`}
        actions={
          <div
            className="flex text-xs font-bold ring-1 ring-line"
            role="group"
            aria-label="Source view"
          >
            {(['raw', 'sanitized'] as const).map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => setView(v)}
                aria-pressed={view === v}
                className={cn(
                  'px-2.5 py-1 capitalize',
                  view === v ? 'bg-ink text-white' : 'bg-white text-ink-muted',
                )}
              >
                {v}
              </button>
            ))}
          </div>
        }
      />
      <pre className="max-h-96 overflow-y-auto px-4 py-3 font-mono text-[12.5px] leading-relaxed break-words whitespace-pre-wrap">
        {content}
      </pre>
    </Card>
  )
}
