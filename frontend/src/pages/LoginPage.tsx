import { zodResolver } from '@hookform/resolvers/zod'
import { ArrowRight, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { z } from 'zod'
import { Button } from '@/components/ui/button'
import { Field, Input, Select } from '@/components/ui/form'
import { errorMessage } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { DEMO_ACCOUNTS, DEMO_PASSWORD } from '@/lib/roles'

const schema = z.object({
  email: z.string().email('Enter a valid email'),
  password: z.string().min(1, 'Password is required'),
})
type LoginForm = z.infer<typeof schema>

export default function LoginPage() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const from = (useLocation().state as { from?: string } | null)?.from ?? '/'
  const [busy, setBusy] = useState(false)
  const form = useForm<LoginForm>({ resolver: zodResolver(schema) })

  if (user) return <Navigate to={from} replace />

  const fillDemo = (email: string) => {
    form.setValue('email', email, { shouldValidate: true })
    form.setValue('password', DEMO_PASSWORD, { shouldValidate: true })
  }

  const signIn = async (email: string, password: string) => {
    setBusy(true)
    try {
      await login(email, password)
      navigate(from, { replace: true })
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-full lg:grid-cols-[1.1fr_1fr]">
      <section className="relative hidden flex-col justify-between overflow-hidden bg-ink p-12 text-white lg:flex">
        <div className="flex items-center gap-3">
          <svg viewBox="0 0 32 32" className="size-9" aria-hidden>
            <path d="M5 26 L16 6 L27 26 Z" fill="none" stroke="#FFE600" strokeWidth="3.5" />
          </svg>
          <span className="text-2xl font-bold">OpsPilot</span>
        </div>
        <div className="max-w-lg">
          <div className="mb-6 h-1.5 w-16 bg-accent" />
          <h1 className="text-5xl leading-[1.05] font-bold text-white">
            AI agents propose.
            <br />
            Humans decide.
            <br />
            <span className="text-accent">Everything is audited.</span>
          </h1>
          <p className="mt-6 text-base text-white/70">
            Operational requests — from inbox to closure — with grounded extraction, explainable
            risk, policy-driven approvals and a tamper-evident audit trail.
          </p>
        </div>
        <p className="flex items-center gap-2 text-xs text-white/50">
          <ShieldCheck className="size-4" /> Prompt-injection guarded · Role-based approvals ·
          Hash-chained audit log
        </p>
      </section>

      <section className="flex items-center justify-center p-6">
        <div className="w-full max-w-md">
          <h2 className="text-2xl">Sign in</h2>
          <p className="mt-1 text-ink-muted">Use your work account or pick a demo account.</p>
          <form
            className="mt-6 space-y-4"
            onSubmit={form.handleSubmit((v) => signIn(v.email, v.password))}
            noValidate
          >
            <Field
              label="Demo account"
              htmlFor="demo-account"
              hint={`Fills in the email and password (${DEMO_PASSWORD}).`}
            >
              <Select id="demo-account" defaultValue="" onChange={(e) => fillDemo(e.target.value)}>
                <option value="" disabled>
                  Choose a demo account…
                </option>
                {DEMO_ACCOUNTS.map((a) => (
                  <option key={a.email} value={a.email}>
                    {a.label} — {a.hint}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Email" htmlFor="email" error={form.formState.errors.email?.message}>
              <Input id="email" type="email" autoComplete="username" {...form.register('email')} />
            </Field>
            <Field
              label="Password"
              htmlFor="password"
              error={form.formState.errors.password?.message}
            >
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                {...form.register('password')}
              />
            </Field>
            <Button type="submit" variant="primary" size="lg" className="w-full" loading={busy}>
              Sign in <ArrowRight />
            </Button>
          </form>
        </div>
      </section>
    </div>
  )
}
