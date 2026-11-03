import { Sparkles } from 'lucide-react'
import { SourceBadge } from '@/components/common/badges'
import type { ApprovalAdvice } from '@/lib/types'

const LABEL: Record<ApprovalAdvice['suggestion'], string> = {
  approve: 'Approve',
  reject: 'Reject',
  forward: 'Forward to the Director',
}

/** The AI's suggested decision for the approver. Advice only: the buttons below decide. */
export function ApprovalAdviceCard({ advice }: { advice: ApprovalAdvice }) {
  return (
    <div className="mt-2 rounded border border-line bg-page p-2 text-sm">
      <p className="flex flex-wrap items-center gap-2">
        <Sparkles className="size-4" />
        <span className="font-bold">AI suggests: {LABEL[advice.suggestion]}</span>
        <SourceBadge source={advice.model === 'rule-based' ? 'fallback' : 'llm'} />
        <span className="text-xs text-ink-muted">Advice only. You decide.</span>
      </p>
      <p className="mt-1">{advice.rationale}</p>
      {advice.checks.length > 0 && (
        <ul className="mt-1 list-disc pl-5 text-xs text-ink-muted">
          {advice.checks.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
