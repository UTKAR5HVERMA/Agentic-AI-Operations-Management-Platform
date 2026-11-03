import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'

export default function NotFoundPage() {
  return (
    <div className="flex flex-col items-center gap-3 py-24 text-center">
      <p className="text-6xl font-bold text-line-strong">404</p>
      <h1 className="text-xl">Page not found</h1>
      <Button asChild variant="primary">
        <Link to="/">Back to dashboard</Link>
      </Button>
    </div>
  )
}
