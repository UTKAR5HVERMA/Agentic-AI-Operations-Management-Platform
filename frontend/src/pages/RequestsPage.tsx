import { PlusSquare, Search } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader, QueryState } from '@/components/common/states'
import { RequestsTable } from '@/components/request/RequestsTable'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input, Select } from '@/components/ui/form'
import { useRequests } from '@/hooks/queries'
import { useAuth } from '@/lib/auth'
import type { RequestFilters } from '@/hooks/queries'
import { ALL_CATEGORIES, ALL_STATUSES, CATEGORY_LABEL, STATUS_LABEL } from '@/lib/labels'

export default function RequestsPage() {
  const isRequester = useAuth().user?.role === 'requester'
  const [filters, setFilters] = useState<RequestFilters>({})
  const [search, setSearch] = useState('')
  const requests = useRequests({ ...filters, q: search.trim() || undefined })
  const set = (patch: RequestFilters) => setFilters((f) => ({ ...f, ...patch }))

  return (
    <>
      <PageHeader
        title={isRequester ? 'My requests' : 'Requests'}
        subtitle={
          isRequester
            ? 'Track the requests you have raised'
            : 'Every operational request, from intake to closure'
        }
        actions={
          !isRequester && (
            <Button asChild variant="primary">
              <Link to="/requests/new">
                <PlusSquare /> New request
              </Link>
            </Button>
          )
        }
      />
      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b border-line p-3">
          <div className="relative w-72">
            <Search className="absolute top-2.5 left-2.5 size-4 text-ink-muted" />
            <Input
              aria-label="Search by ref or subject"
              placeholder="Search ref or subject"
              className="pl-8"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          {!isRequester && (
            <>
              <Select
                aria-label="Status"
                className="w-44"
                value={filters.status ?? ''}
                onChange={(e) => set({ status: e.target.value || undefined })}
              >
                <option value="">All statuses</option>
                {ALL_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {STATUS_LABEL[s]}
                  </option>
                ))}
              </Select>
              <Select
                aria-label="Priority"
                className="w-36"
                value={filters.priority ?? ''}
                onChange={(e) => set({ priority: e.target.value || undefined })}
              >
                <option value="">Any priority</option>
                {['P1', 'P2', 'P3', 'P4'].map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </Select>
              <Select
                aria-label="Category"
                className="w-48"
                value={filters.category ?? ''}
                onChange={(e) => set({ category: e.target.value || undefined })}
              >
                <option value="">All categories</option>
                {ALL_CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {CATEGORY_LABEL[c]}
                  </option>
                ))}
              </Select>
              <label className="flex items-center gap-2 text-sm font-bold">
                <input
                  type="checkbox"
                  className="size-4 accent-ink"
                  checked={Boolean(filters.mine)}
                  onChange={(e) => set({ mine: e.target.checked || undefined })}
                />
                Mine
              </label>
            </>
          )}
        </div>
        <QueryState query={requests}>
          {(rows) => <RequestsTable rows={rows} simple={isRequester} />}
        </QueryState>
      </Card>
    </>
  )
}
