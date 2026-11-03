import type { Category, Role, Status } from './types'

export const ROLE_LABEL: Record<Role, string> = {
  requester: 'Requester',
  ops_analyst: 'Operations Team',
  ops_manager: 'Regional Manager',
  admin: 'Director (Admin)',
}

export const STATUS_LABEL: Record<Status, string> = {
  NEW: 'New',
  ANALYZING: 'Analyzing',
  NEEDS_INFO: 'Needs info',
  PENDING_REVIEW: 'Pending review',
  PENDING_APPROVAL: 'Pending approval',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
  ESCALATED: 'Escalated',
  IN_PROGRESS: 'In progress',
  RESOLVED: 'Resolved',
  CLOSED: 'Closed',
  DUPLICATE: 'Duplicate',
  ON_HOLD: 'On hold',
  CANCELLED: 'Cancelled',
}

export const CATEGORY_LABEL: Record<Category, string> = {
  delivery_delay: 'Delivery delay',
  inventory_shortage: 'Inventory shortage',
  supplier_issue: 'Supplier issue',
  urgent_approval: 'Urgent approval',
  customer_commitment: 'Customer commitment',
  other: 'Other',
}

export const FIELD_LABEL: Record<string, string> = {
  supplier: 'Supplier',
  item: 'Item',
  quantity_required: 'Quantity required',
  quantity_available: 'Quantity available',
  location: 'Location',
  required_date: 'Required date',
  delay_days: 'Delay (days)',
  event: 'Dependency / event',
  cost_impact: 'Cost impact',
  requested_action: 'Requested action',
  approval_deadline: 'Approval deadline',
  original_delivery_date: 'Original delivery date',
}

export const AGENT_LABEL: Record<string, string> = {
  intake_guard: 'Intake & safety',
  extraction: 'Extraction',
  validation: 'Validation',
  dedup: 'Duplicate check',
  ops_risk: 'Ops risk',
  financial_risk: 'Financial risk',
  reconciler: 'Risk reconciler',
  recommendation: 'Recommendations',
  score: 'Confidence gate',
  approval_router: 'Approval routing',
  communication: 'Drafts',
}

export const ALL_STATUSES = Object.keys(STATUS_LABEL) as Status[]
export const ALL_CATEGORIES = Object.keys(CATEGORY_LABEL) as Category[]

/** Plain business status shown to requesters (the internal lifecycle stays with the ops team). */
export function requesterStatus(status: Status, awaitingRole: Role | null): string {
  switch (status) {
    case 'NEW':
      return 'Submitted'
    case 'ANALYZING':
    case 'PENDING_REVIEW':
      return 'Under review'
    case 'NEEDS_INFO':
      return 'More information needed'
    case 'PENDING_APPROVAL':
    case 'ESCALATED':
      return awaitingRole === 'admin'
        ? 'Director approval pending'
        : 'Regional Manager approval pending'
    case 'APPROVED':
    case 'IN_PROGRESS':
      return 'Approved – action in progress'
    case 'REJECTED':
      return 'Rejected – alternative being prepared'
    case 'ON_HOLD':
      return 'On hold'
    case 'RESOLVED':
      return 'Resolved'
    case 'CLOSED':
      return 'Closed'
    case 'CANCELLED':
      return 'Cancelled'
    case 'DUPLICATE':
      return 'Merged with an existing request'
  }
}
