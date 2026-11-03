import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { Send, Sparkles } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { z } from 'zod'
import { PageHeader } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Field, Input, Select, Textarea } from '@/components/ui/form'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useCaseAction, useSamples } from '@/hooks/queries'
import { errorMessage, post } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { Channel, CreateRequestBody, RequestDetail } from '@/lib/types'

const schema = z.object({
  channel: z.enum(['email', 'manual', 'whatsapp', 'phone']),
  subject: z.string().trim().min(1, 'Subject is required').max(300),
  sender_name: z.string().trim().max(120).optional(),
  sender_email: z.union([z.literal(''), z.string().trim().email('Enter a valid email')]).optional(),
  raw_text: z.string().trim().min(1, 'Please describe the request').max(20_000),
})
type FormValues = z.infer<typeof schema>
type Mode = 'email' | 'message'

const MESSAGE_CHANNELS: { value: Channel; label: string }[] = [
  { value: 'phone', label: 'Phone call' },
  { value: 'whatsapp', label: 'WhatsApp' },
  { value: 'manual', label: 'Other message / note' },
]

interface Composed {
  subject: string
  body: string
  model: string
  note: string | null
}

export default function NewRequestPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const isRequester = user?.role === 'requester'
  const samples = useSamples()
  const [mode, setMode] = useState<Mode>('email')
  // Requests reach the ops mailbox from anyone. For the demo the request desk picks who is
  // sending, using the sample senders as personas (one source of truth: GET /samples).
  const senders = useMemo(() => {
    const seen = new Map<string, { email: string; name: string; sampleId: string }>()
    for (const s of samples.data ?? [])
      if (s.sender_email && s.sender_name && !seen.has(s.sender_email))
        seen.set(s.sender_email, { email: s.sender_email, name: s.sender_name, sampleId: s.id })
    return [...seen.values()]
  }, [samples.data])
  const [senderEmail, setSenderEmail] = useState('')
  const persona = senders.find((s) => s.email === senderEmail) ?? senders[0]
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { channel: 'phone' },
  })
  const errors = form.formState.errors

  const create = useCaseAction(
    (body: CreateRequestBody) => post<RequestDetail>('/requests', body),
    (r) => `Request ${r.ref} submitted`,
  )
  const compose = useMutation({
    mutationFn: () =>
      post<Composed>('/requests/compose', {
        subject: form.getValues('subject') || null,
        text: form.getValues('raw_text'),
        sender_name: isRequester ? persona?.name : form.getValues('sender_name') || null,
      }),
    onSuccess: (r) => {
      form.setValue('subject', r.subject, { shouldValidate: true })
      form.setValue('raw_text', r.body, { shouldValidate: true })
      if (r.note) toast.warning(r.note)
      else toast.success('Email generated — review it before submitting')
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  const loadSample = (id: string) => {
    const s = samples.data?.find((x) => x.id === id)
    if (!s) return
    setMode(s.channel === 'email' ? 'email' : 'message')
    form.reset({
      channel: s.channel === 'email' ? 'phone' : s.channel,
      subject: s.subject,
      raw_text: s.raw_text,
      sender_name: s.sender_name ?? '',
      sender_email: s.sender_email ?? '',
    })
  }

  const submit = form.handleSubmit((v) =>
    create.mutate(
      {
        subject: v.subject,
        raw_text: v.raw_text,
        channel: mode === 'email' ? 'email' : v.channel,
        // The request desk sends on behalf of the chosen demo sender; updates go back to them.
        sender_email: isRequester ? (persona?.email ?? user?.email) : v.sender_email || null,
        sender_name: isRequester ? (persona?.name ?? user?.name) : v.sender_name || null,
      },
      { onSuccess: (r) => navigate(`/requests/${r.id}`) },
    ),
  )
  const body = useWatch({ control: form.control, name: 'raw_text' })
  const bodyLength = (body ?? '').trim().length

  return (
    <>
      <PageHeader
        title="New request"
        subtitle={
          isRequester
            ? 'Write an email or log a message. The operations team will review it and keep you updated.'
            : 'Paste an email or log a message. AI agents analyse it in the background; nothing is approved or sent without a human.'
        }
      />
      <Card>
        <CardHeader
          title="Request details"
          actions={
            !isRequester && (
              <Select
                aria-label="Load sample"
                className="w-64"
                value=""
                onChange={(e) => loadSample(e.target.value)}
                disabled={!samples.data}
              >
                <option value="">Load sample scenario…</option>
                {samples.data?.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </Select>
            )
          }
        />
        <CardBody>
          {isRequester && (
            <div className="mb-5 flex flex-wrap items-end gap-3 border-b border-line pb-5">
              <div className="w-full max-w-md">
                <Field
                  label="Send as (demo sender)"
                  htmlFor="persona"
                  hint="In production, requests arrive at the operations mailbox from anyone."
                >
                  <Select
                    id="persona"
                    value={persona?.email ?? ''}
                    onChange={(e) => setSenderEmail(e.target.value)}
                    disabled={!senders.length}
                  >
                    {senders.map((s) => (
                      <option key={s.email} value={s.email}>
                        {s.name} · {s.email}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>
              <Button
                type="button"
                variant="ghost"
                disabled={!persona}
                onClick={() => persona && loadSample(persona.sampleId)}
                className="mb-5"
              >
                Use their sample message
              </Button>
            </div>
          )}
          <Tabs value={mode} onValueChange={(v) => setMode(v as Mode)}>
            <TabsList>
              <TabsTrigger value="email">Email</TabsTrigger>
              <TabsTrigger value="message">Message</TabsTrigger>
            </TabsList>
          </Tabs>
          <form className="mt-5 grid gap-4 lg:grid-cols-2" onSubmit={submit} noValidate>
            {mode === 'message' && (
              <div className="lg:col-span-2">
                <Field label="Received via" htmlFor="channel">
                  <Select id="channel" className="lg:w-1/2" {...form.register('channel')}>
                    {MESSAGE_CHANNELS.map((c) => (
                      <option key={c.value} value={c.value}>
                        {c.label}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>
            )}
            {!isRequester && (
              <>
                <Field
                  label="From (name)"
                  htmlFor="sender_name"
                  error={errors.sender_name?.message}
                >
                  <Input id="sender_name" {...form.register('sender_name')} />
                </Field>
                <Field
                  label="From (email)"
                  htmlFor="sender_email"
                  error={errors.sender_email?.message}
                >
                  <Input id="sender_email" type="email" {...form.register('sender_email')} />
                </Field>
              </>
            )}
            <div className="lg:col-span-2">
              <Field label="Subject" htmlFor="subject" error={errors.subject?.message}>
                <Input id="subject" {...form.register('subject')} />
              </Field>
            </div>
            <div className="lg:col-span-2">
              <Field
                label={mode === 'email' ? 'Email' : 'Message'}
                htmlFor="raw_text"
                error={errors.raw_text?.message}
                hint={
                  mode === 'email'
                    ? 'Write it your way, then use “Generate email with AI” to turn it into a clear email.'
                    : 'What happened, which items and location, and when it is needed.'
                }
              >
                <Textarea id="raw_text" className="min-h-[42vh]" {...form.register('raw_text')} />
              </Field>
            </div>
            <div className="flex flex-wrap justify-end gap-3 lg:col-span-2">
              {mode === 'email' && (
                <Button
                  type="button"
                  size="lg"
                  variant="dark"
                  loading={compose.isPending}
                  disabled={bodyLength < 3}
                  onClick={() => compose.mutate()}
                >
                  <Sparkles /> Generate email with AI
                </Button>
              )}
              <Button type="submit" variant="primary" size="lg" loading={create.isPending}>
                <Send /> Submit request
              </Button>
            </div>
          </form>
        </CardBody>
      </Card>
    </>
  )
}
