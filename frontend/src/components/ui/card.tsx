import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <section className={cn('rounded-md border border-line bg-white', className)} {...props} />
}

interface CardHeaderProps {
  title: ReactNode
  subtitle?: ReactNode
  icon?: ReactNode
  actions?: ReactNode
  className?: string
}

export function CardHeader({ title, subtitle, icon, actions, className }: CardHeaderProps) {
  return (
    <header
      className={cn(
        'flex items-start justify-between gap-3 border-b border-line px-4 py-3',
        className,
      )}
    >
      <div className="flex min-w-0 items-start gap-2">
        {icon && <span className="mt-0.5 text-ink-muted [&_svg]:size-4">{icon}</span>}
        <div className="min-w-0">
          <h2 className="text-[15px] leading-5">{title}</h2>
          {subtitle && <p className="mt-0.5 text-xs text-ink-muted">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  )
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('p-4', className)} {...props} />
}
