// Confidence bands shared by the meter and tests (BACKEND.md §7.4 thresholds).
export function confidenceLevel(value: number): { label: string; tone: string; bar: string } {
  if (value >= 0.8) return { label: 'High', tone: 'text-ok', bar: 'bg-ok' }
  if (value >= 0.5) return { label: 'Needs review', tone: 'text-[#a85700]', bar: 'bg-warn' }
  return { label: 'Low', tone: 'text-bad', bar: 'bg-bad' }
}
