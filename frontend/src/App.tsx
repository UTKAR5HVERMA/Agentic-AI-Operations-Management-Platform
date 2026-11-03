import { QueryClientProvider } from '@tanstack/react-query'
import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Toaster } from 'sonner'
import { LoadingState } from '@/components/common/states'
import { AppShell, ProtectedRoute } from '@/components/layout/AppShell'
import { TooltipProvider } from '@/components/ui/tooltip'
import { AuthProvider } from '@/lib/auth'
import { queryClient } from '@/lib/queryClient'
import { APPROVER_ROLES, STAFF_ROLES } from '@/lib/roles'
import LoginPage from '@/pages/LoginPage'

// Pages load on demand so the login screen stays light (charts/markdown live in their own chunks).
const ApprovalsPage = lazy(() => import('@/pages/ApprovalsPage'))
const AuditPage = lazy(() => import('@/pages/AuditPage'))
const DashboardPage = lazy(() => import('@/pages/DashboardPage'))
const NewRequestPage = lazy(() => import('@/pages/NewRequestPage'))
const NotFoundPage = lazy(() => import('@/pages/NotFoundPage'))
const ReportsPage = lazy(() => import('@/pages/ReportsPage'))
const RequestDetailPage = lazy(() => import('@/pages/RequestDetailPage'))
const RequestsPage = lazy(() => import('@/pages/RequestsPage'))
const ScenarioLabPage = lazy(() => import('@/pages/ScenarioLabPage'))

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <AuthProvider>
          <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
            <Suspense fallback={<LoadingState />}>
              <Routes>
                <Route path="/login" element={<LoginPage />} />
                <Route element={<AppShell />}>
                  <Route index element={<DashboardPage />} />
                  <Route path="requests" element={<RequestsPage />} />
                  <Route path="requests/new" element={<NewRequestPage />} />
                  <Route path="requests/:id" element={<RequestDetailPage />} />
                  <Route
                    path="approvals"
                    element={
                      <ProtectedRoute roles={APPROVER_ROLES}>
                        <ApprovalsPage />
                      </ProtectedRoute>
                    }
                  />
                  <Route
                    path="reports"
                    element={
                      <ProtectedRoute roles={STAFF_ROLES}>
                        <ReportsPage />
                      </ProtectedRoute>
                    }
                  />
                  <Route
                    path="audit"
                    element={
                      <ProtectedRoute roles={STAFF_ROLES}>
                        <AuditPage />
                      </ProtectedRoute>
                    }
                  />
                  <Route
                    path="lab"
                    element={
                      <ProtectedRoute roles={['admin']}>
                        <ScenarioLabPage />
                      </ProtectedRoute>
                    }
                  />
                  <Route path="*" element={<NotFoundPage />} />
                </Route>
              </Routes>
            </Suspense>
          </BrowserRouter>
          <Toaster
            position="top-center"
            toastOptions={{ classNames: { toast: 'rounded-sm border-l-4 border-l-accent' } }}
            richColors
            closeButton
          />
        </AuthProvider>
      </TooltipProvider>
    </QueryClientProvider>
  )
}
