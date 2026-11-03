import type { Role } from './types'

export const APPROVER_ROLES: Role[] = ['ops_manager']
export const STAFF_ROLES: Role[] = ['ops_analyst', 'ops_manager']

export const DEMO_PASSWORD = 'Demo@123' // documented demo credential (README), not a secret

export const DEMO_ACCOUNTS: { label: string; email: string; hint: string }[] = [
  { label: 'Requester', email: 'requester@opspilot.demo', hint: 'Request desk: send as anyone' },
  {
    label: 'Operations Team',
    email: 'ops.team@opspilot.demo',
    hint: 'Reviews AI analysis, routes for approval',
  },
  {
    label: 'Regional Manager (West)',
    email: 'manager@opspilot.demo',
    hint: 'Decides ≤ ₹50,000; forwards above',
  },
  {
    label: 'Regional Manager (North)',
    email: 'manager.north@opspilot.demo',
    hint: 'Decides when the team assigns them',
  },
  {
    label: 'Director (Admin)',
    email: 'admin@opspilot.demo',
    hint: 'Decides forwarded approvals · Lab',
  },
]
