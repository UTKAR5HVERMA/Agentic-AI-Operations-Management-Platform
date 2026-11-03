import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, ApiError, errorMessage } from '@/lib/api'
import type {
  Approval,
  Approver,
  AuditEntry,
  Dashboard,
  Flags,
  Health,
  RequestDetail,
  RequestSummary,
  Sample,
} from '@/lib/types'

export interface RequestFilters {
  status?: string
  priority?: string
  category?: string
  q?: string
  mine?: boolean
}

const qs = (params: Record<string, string | boolean | number | undefined>) => {
  const entries = Object.entries(params).filter(
    ([, v]) => v !== undefined && v !== '' && v !== false,
  )
  return entries.length ? `?${new URLSearchParams(entries.map(([k, v]) => [k, String(v)]))}` : ''
}

export const useHealth = () =>
  useQuery({ queryKey: ['health'], queryFn: () => api<Health>('/health'), refetchInterval: 15_000 })

export const useRequests = (filters: RequestFilters) =>
  useQuery({
    queryKey: ['requests', filters],
    queryFn: () => api<RequestSummary[]>(`/requests${qs({ ...filters })}`),
    refetchInterval: 20_000,
  })

const ANALYSING = new Set(['NEW', 'ANALYZING'])
const WAITING = new Set(['PENDING_APPROVAL', 'ESCALATED'])

export const useRequest = (id: string) =>
  useQuery({
    queryKey: ['request', id],
    queryFn: () => api<RequestDetail>(`/requests/${id}`),
    refetchInterval: (query) =>
      ANALYSING.has(query.state.data?.status ?? '')
        ? 2_500 // background analysis: refresh quickly until results land
        : WAITING.has(query.state.data?.status ?? '')
          ? 10_000
          : false,
  })

export const useApprovals = (status: string, mine: boolean, enabled = true) =>
  useQuery({
    queryKey: ['approvals', status, mine],
    queryFn: () => api<Approval[]>(`/approvals${qs({ status, mine })}`),
    refetchInterval: 20_000,
    enabled,
  })

export const useDashboard = (enabled = true) =>
  useQuery({
    queryKey: ['dashboard'],
    queryFn: () => api<Dashboard>('/reports/dashboard'),
    refetchInterval: 30_000,
    enabled,
  })

export const useApprovers = () =>
  useQuery({
    queryKey: ['approvers'],
    queryFn: () => api<Approver[]>('/approvals/approvers'),
    staleTime: Infinity,
  })

export const useSamples = () =>
  useQuery({ queryKey: ['samples'], queryFn: () => api<Sample[]>('/samples'), staleTime: Infinity })

export const useFlags = () =>
  useQuery({ queryKey: ['flags'], queryFn: () => api<Flags>('/admin/flags') })

export const useAudit = (params: Record<string, string | undefined>) =>
  useQuery({ queryKey: ['audit', params], queryFn: () => api<AuditEntry[]>(`/audit${qs(params)}`) })

/**
 * Mutation that toasts success/errors and refreshes everything case-related afterwards.
 * 409 STALE_VERSION reloads the case (FRONTEND.md §5.5).
 */
export function useCaseAction<TVars, TResult = unknown>(
  fn: (vars: TVars) => Promise<TResult>,
  successMessage?: string | ((result: TResult) => string),
) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (result) => {
      if (successMessage)
        toast.success(
          typeof successMessage === 'function' ? successMessage(result) : successMessage,
        )
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 403)
        toast.error(errorMessage(error), { duration: 6000 })
      else toast.error(errorMessage(error))
    },
    onSettled: () => {
      for (const key of [
        'request',
        'requests',
        'approvals',
        'dashboard',
        'audit',
        'health',
        'flags',
      ])
        client.invalidateQueries({ queryKey: [key] })
    },
  })
}
