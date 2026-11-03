// Single entry point for server calls (FRONTEND.md §7). Components never call fetch directly.

export const TOKEN_KEY = 'opspilot.token'

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    public code?: string,
  ) {
    super(detail)
  }
}

export async function api<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem(TOKEN_KEY)
  let res: Response
  try {
    res = await fetch(`/api${path}`, {
      ...opts,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...opts.headers,
      },
    })
  } catch {
    throw new ApiError(0, "Couldn't reach the server. Check your connection and retry.", 'NETWORK')
  }
  if (res.status === 401 && token && path !== '/auth/login') {
    localStorage.removeItem(TOKEN_KEY)
    window.location.assign('/login')
  }
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: unknown; code?: string }
    const detail = typeof body.detail === 'string' ? body.detail : res.statusText
    throw new ApiError(res.status, detail || 'Request failed', body.code)
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
}

export const post = <T>(path: string, body: unknown = {}) =>
  api<T>(path, { method: 'POST', body: JSON.stringify(body) })
export const patch = <T>(path: string, body: unknown) =>
  api<T>(path, { method: 'PATCH', body: JSON.stringify(body) })
export const put = <T>(path: string, body: unknown) =>
  api<T>(path, { method: 'PUT', body: JSON.stringify(body) })
export const del = (path: string) => api<void>(path, { method: 'DELETE' })

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'STALE_VERSION') return 'This case was updated by someone else — reloaded.'
    return error.detail
  }
  return error instanceof Error ? error.message : 'Something went wrong'
}
