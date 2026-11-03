import { Link, Navigate, Outlet, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { LoadingState } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import { Lock } from 'lucide-react'
import { useAuth } from '@/lib/auth'
import type { Role } from '@/lib/types'
import { HealthBar } from './HealthBar'
import { RequesterTopBar } from './RequesterTopBar'
import { Sidebar } from './Sidebar'

export function AppShell() {
  const { user, loading, signedOut } = useAuth()
  const location = useLocation()
  if (loading) return <LoadingState label="Restoring session…" />
  // Only deep links return to their page; after sign-out the next user (maybe another role) starts fresh.
  if (!user)
    return (
      <Navigate to="/login" replace state={signedOut ? undefined : { from: location.pathname }} />
    )
  if (user.role === 'requester')
    return (
      <div className="flex h-full flex-col">
        <RequesterTopBar />
        <main className="flex-1 overflow-y-auto px-8 py-6">
          <Outlet />
        </main>
      </div>
    )
  return (
    <div className="flex h-full">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <HealthBar />
        <main className="flex-1 overflow-y-auto px-8 py-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

/** Route-level guard. The backend still enforces RBAC; this only avoids dead-end screens. */
export function ProtectedRoute({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { hasRole } = useAuth()
  if (hasRole(...roles)) return <>{children}</>
  return (
    <div className="flex flex-col items-center gap-2 py-24 text-center">
      <Lock className="size-10 text-line-strong" />
      <h1 className="text-xl">You don&apos;t have access</h1>
      <p className="text-ink-muted">
        This area is limited to other roles. Ask an admin if you need it.
      </p>
      <Button asChild variant="primary" className="mt-4">
        <Link to="/">Go to dashboard</Link>
      </Button>
    </div>
  )
}
