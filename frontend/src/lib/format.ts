import { formatDistanceToNowStrict } from 'date-fns'

const inr = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
})
const istDateTime = new Intl.DateTimeFormat('en-IN', {
  timeZone: 'Asia/Kolkata',
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hour12: true,
})

export const formatInr = (amount: number) => inr.format(amount)
export const formatPct = (value: number) => `${Math.round(value * 100)}%`
export const formatIst = (iso: string | null | undefined) =>
  iso ? `${istDateTime.format(new Date(iso))} IST` : '—'
export const timeAgo = (iso: string) => `${formatDistanceToNowStrict(new Date(iso))} ago`

/** "3h 12m" style duration from milliseconds. */
export function formatDuration(ms: number): string {
  const minutes = Math.floor(Math.abs(ms) / 60_000)
  const days = Math.floor(minutes / 1440)
  const hours = Math.floor((minutes % 1440) / 60)
  const mins = minutes % 60
  if (days > 0) return `${days}d ${hours}h`
  if (hours > 0) return `${hours}h ${mins}m`
  return `${mins}m`
}

export const titleCase = (value: string) =>
  value.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
