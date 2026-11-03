import { useEffect, useState } from 'react'

/** Milliseconds until `target` (negative once passed), re-rendering every `intervalMs`. */
export function useCountdown(
  target: string | null | undefined,
  intervalMs = 30_000,
): number | null {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!target) return
    const id = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(id)
  }, [target, intervalMs])
  return target ? new Date(target).getTime() - now : null
}
