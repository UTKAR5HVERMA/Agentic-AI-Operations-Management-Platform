import { LogOut, PlusSquare } from 'lucide-react'
import { Link, NavLink } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/lib/auth'
import { cn } from '@/lib/utils'

/** Requester navigation: a single charcoal bar (no sidebar, no dashboard). */
export function RequesterTopBar() {
  const { user, logout } = useAuth()
  return (
    <header className="flex h-14 shrink-0 items-center gap-8 bg-ink px-6 text-white">
      <Link to="/requests" className="flex items-center gap-2.5">
        <svg viewBox="0 0 32 32" className="size-6" aria-hidden>
          <path d="M5 26 L16 6 L27 26 Z" fill="none" stroke="#FFE600" strokeWidth="3.5" />
        </svg>
        <span className="text-lg font-bold">OpsPilot</span>
      </Link>
      <nav aria-label="Main">
        <NavLink
          to="/requests"
          end
          className={({ isActive }) =>
            cn(
              'border-b-[3px] py-4 text-sm font-bold',
              isActive
                ? 'border-accent text-white'
                : 'border-transparent text-white/70 hover:text-white',
            )
          }
        >
          My requests
        </NavLink>
      </nav>
      <div className="ml-auto flex items-center gap-5">
        <Button asChild variant="primary" size="sm">
          <Link to="/requests/new">
            <PlusSquare /> New request
          </Link>
        </Button>
        {user && (
          <span className="text-right text-xs leading-tight">
            <span className="block font-bold">{user.name}</span>
            <span className="text-white/60">{user.region}</span>
          </span>
        )}
        <button
          type="button"
          onClick={logout}
          aria-label="Sign out"
          className="rounded-sm p-1.5 text-white/70 hover:bg-white/10 hover:text-accent"
        >
          <LogOut className="size-4" />
        </button>
      </div>
    </header>
  )
}
