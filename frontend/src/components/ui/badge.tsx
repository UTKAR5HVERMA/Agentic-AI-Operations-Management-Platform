import { cva } from 'class-variance-authority'
import type { VariantProps } from 'class-variance-authority'
import type { HTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1 whitespace-nowrap rounded-sm px-1.5 py-0.5 text-[11px] font-bold uppercase tracking-wide [&_svg]:size-3',
  {
    variants: {
      tone: {
        neutral: 'bg-page text-ink-muted ring-1 ring-line',
        dark: 'bg-ink text-white',
        accent: 'bg-accent text-ink',
        ok: 'bg-ok/10 text-ok',
        warn: 'bg-warn/15 text-[#a85700]',
        bad: 'bg-bad/10 text-bad',
        info: 'bg-info/10 text-info',
        teal: 'bg-teal/10 text-[#167a78]',
        violet: 'bg-violet/10 text-violet',
      },
    },
    defaultVariants: { tone: 'neutral' },
  },
)

export type BadgeTone = NonNullable<VariantProps<typeof badgeVariants>['tone']>

export function Badge({
  className,
  tone,
  ...props
}: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />
}
