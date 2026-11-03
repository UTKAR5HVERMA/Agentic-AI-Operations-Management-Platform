import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api, post, TOKEN_KEY } from './api'
import { queryClient } from './queryClient'
import type { LoginResponse, Role, User } from './types'

interface AuthState {
  user: User | null
  loading: boolean
  /** True after an explicit sign-out: the next login starts on the dashboard, not the old page. */
  signedOut: boolean
  login: (email: string, password: string) => Promise<User>
  logout: () => void
  hasRole: (...roles: Role[]) => boolean
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(() => Boolean(localStorage.getItem(TOKEN_KEY)))
  const [signedOut, setSignedOut] = useState(false)

  useEffect(() => {
    if (!localStorage.getItem(TOKEN_KEY)) return
    api<User>('/auth/me')
      .then(setUser)
      .catch(() => localStorage.removeItem(TOKEN_KEY))
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const res = await post<LoginResponse>('/auth/login', { email, password })
    localStorage.setItem(TOKEN_KEY, res.access_token)
    queryClient.clear()
    setSignedOut(false)
    setUser(res.user)
    return res.user
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    queryClient.clear()
    setSignedOut(true)
    setUser(null)
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      signedOut,
      login,
      logout,
      hasRole: (...roles) => Boolean(user && (user.role === 'admin' || roles.includes(user.role))),
    }),
    [user, loading, signedOut, login, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
