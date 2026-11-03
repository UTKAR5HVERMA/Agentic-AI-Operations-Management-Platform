import {
  CheckSquare,
  FlaskConical,
  LayoutDashboard,
  ListChecks,
  LogOut,
  PlusSquare,
  ScrollText,
  BarChart3,
} from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { useApprovals } from '@/hooks/queries'
import { useAuth } from '@/lib/auth'
import { ROLE_LABEL } from '@/lib/labels'
import { APPROVER_ROLES, STAFF_ROLES } from '@/lib/roles'
import type { Role } from '@/lib/types'
import { cn } from '@/lib/utils'

interface NavItem {
  to: string
  label: string
  icon: typeof LayoutDashboard
  roles?: Role[]
  badge?: number
}

export function Sidebar() {
  const { user, hasRole, logout } = useAuth()
  const isApprover = hasRole(...APPROVER_ROLES)
  const pending = useApprovals('pending', true, isApprover)

  const items: NavItem[] = [
    { to: '/', label: 'Dashboard', icon: LayoutDashboard },
    { to: '/requests', label: 'Requests', icon: ListChecks },
    { to: '/requests/new', label: 'New request', icon: PlusSquare },
    {
      to: '/approvals',
      label: 'Approvals',
      icon: CheckSquare,
      roles: APPROVER_ROLES,
      badge: pending.data?.filter((a) => a.can_decide).length,
    },
    { to: '/reports', label: 'Reports', icon: BarChart3, roles: STAFF_ROLES },
    { to: '/audit', label: 'Audit trail', icon: ScrollText, roles: STAFF_ROLES },
    { to: '/lab', label: 'Scenario Lab', icon: FlaskConical, roles: ['admin'] },
  ]

  return (
    <aside className="flex w-60 shrink-0 flex-col bg-ink text-white">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <svg viewBox="0 0 32 32" className="size-7" aria-hidden>
          <path d="M5 26 L16 6 L27 26 Z" fill="none" stroke="#FFE600" strokeWidth="3.5" />
        </svg>
        <div>
          <p className="text-lg leading-none font-bold">OpsPilot</p>
          <p className="mt-1 text-[10px] tracking-widest text-white/60 uppercase">Operations AI</p>
        </div>
      </div>
      <nav className="flex-1 space-y-0.5 py-2" aria-label="Main">
        {items
          .filter((item) => !item.roles || hasRole(...item.roles))
          .map(({ to, label, icon: Icon, badge }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/' || to === '/requests'}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 border-l-4 px-4 py-2.5 text-sm transition-colors',
                  isActive
                    ? 'border-accent bg-white/10 font-bold text-white'
                    : 'border-transparent text-white/75 hover:bg-white/5 hover:text-white',
                )
              }
            >
              <Icon className="size-4" />
              <span className="flex-1">{label}</span>
              {Boolean(badge) && (
                <span className="rounded-sm bg-accent px-1.5 text-[11px] font-bold text-ink">
                  {badge}
                </span>
              )}
            </NavLink>
          ))}
      </nav>
      {user && (
        <div className="border-t border-white/10 px-5 py-4">
          <p className="truncate font-bold">{user.name}</p>
          <p className="mt-0.5 text-xs text-white/60">
            {ROLE_LABEL[user.role]} · {user.region}
          </p>
          <button
            type="button"
            onClick={logout}
            className="mt-3 inline-flex items-center gap-1.5 text-xs text-white/70 hover:text-accent"
          >
            <LogOut className="size-3.5" /> Sign out
          </button>
        </div>
      )}
    </aside>
  )
}
