import { AlertTriangle, Inbox, Loader2, Lock, RefreshCw } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { ApiError, errorMessage } from '@/lib/api'

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-ink-muted" role="status">
      <Loader2 className="size-4 animate-spin" /> {label}
    </div>
  )
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string
  hint?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center gap-2 py-10 text-center">
      <Inbox className="size-8 text-line-strong" />
      <p className="font-bold">{title}</p>
      {hint && <p className="max-w-sm text-xs text-ink-muted">{hint}</p>}
      {action}
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const forbidden = error instanceof ApiError && error.status === 403
  const Icon = forbidden ? Lock : AlertTriangle
  return (
    <div className="flex flex-col items-center gap-2 py-10 text-center" role="alert">
      <Icon className={forbidden ? 'size-8 text-ink-muted' : 'size-8 text-bad'} />
      <p className="font-bold">{forbidden ? "You don't have access" : "Couldn't load this"}</p>
      <p className="max-w-md text-xs text-ink-muted">{errorMessage(error)}</p>
      {onRetry && !forbidden && (
        <Button size="sm" onClick={onRetry}>
          <RefreshCw /> Retry
        </Button>
      )}
    </div>
  )
}

/** Renders loading / error / content for a query-like object. */
export function QueryState<T>({
  query,
  children,
}: {
  query: { data: T | undefined; isLoading: boolean; error: unknown; refetch: () => unknown }
  children: (data: T) => ReactNode
}) {
  if (query.isLoading) return <LoadingState />
  if (query.error || query.data === undefined)
    return <ErrorState error={query.error} onRetry={() => query.refetch()} />
  return <>{children(query.data)}</>
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string
  subtitle?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="border-l-4 border-accent pl-3 text-2xl leading-tight">{title}</h1>
        {subtitle && <p className="mt-1 pl-4 text-sm text-ink-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}
