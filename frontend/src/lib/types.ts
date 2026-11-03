// Mirrors backend/app/schemas.py and app/enums.py (BACKEND.md §8 + §17). Keep in sync.

export type Role = 'requester' | 'ops_analyst' | 'ops_manager' | 'admin'

export type Status =
  | 'NEW'
  | 'ANALYZING'
  | 'NEEDS_INFO'
  | 'PENDING_REVIEW'
  | 'PENDING_APPROVAL'
  | 'APPROVED'
  | 'REJECTED'
  | 'ESCALATED'
  | 'IN_PROGRESS'
  | 'RESOLVED'
  | 'CLOSED'
  | 'DUPLICATE'
  | 'ON_HOLD'
  | 'CANCELLED'

export type Priority = 'P1' | 'P2' | 'P3' | 'P4'
export type Channel = 'email' | 'manual' | 'whatsapp' | 'phone'
export type Category =
  | 'delivery_delay'
  | 'inventory_shortage'
  | 'supplier_issue'
  | 'urgent_approval'
  | 'customer_commitment'
  | 'other'
export type RiskLevel = 'low' | 'medium' | 'high' | 'critical'
export type FieldSource = 'llm' | 'fallback' | 'human' | 'event'
export type IssueType =
  | 'missing_info'
  | 'conflict'
  | 'ambiguity'
  | 'injection'
  | 'duplicate'
  | 'low_confidence'
  | 'system_unavailable'
  | 'agent_disagreement'
  | 'communication_failure'
  | 'circumstances_changed'
  | 'deadline_missed'
  | 'out_of_bounds'
  | 'extraction_flagged'
export type Severity = 'info' | 'warning' | 'blocker'
export type IssueStatus = 'open' | 'resolved' | 'dismissed'
export type ApprovalStatus =
  'pending' | 'approved' | 'rejected' | 'escalated' | 'expired' | 'cancelled'
export type CommType =
  | 'stakeholder_update'
  | 'approval_request'
  | 'escalation'
  | 'closure'
  | 'management_summary'
  | 'clarification'
  | 'cancellation'
  | 'duplicate_notice'
  | 'reminder'
  | 'requester_reply'
export type CommStatus = 'draft' | 'approved' | 'queued' | 'sent' | 'failed' | 'discarded'
export type EventType =
  'supplier_date_revised' | 'launch_postponed' | 'inventory_updated' | 'stakeholder_reply'
export type ConfidenceBand = 'recommended' | 'needs_review' | 'withheld'

export interface User {
  id: string
  name: string
  email: string
  role: Role
  region: string
  approval_limit_inr: number
}

export interface LoginResponse {
  access_token: string
  token_type: string
  user: User
}

export interface Sender {
  name: string | null
  email: string | null
}

export interface RequestSummary {
  id: string
  ref: string
  subject: string
  status: Status
  priority: Priority
  category: Category
  channel: Channel
  sender: Sender
  region: string
  risk_level: RiskLevel | null
  overall_confidence: number
  degraded: boolean
  injection_flag: boolean
  open_issues: number
  pending_approvals: number
  awaiting_role: Role | null
  deadline_at: string | null
  sla_due_at: string | null
  created_at: string
  updated_at: string
}

export interface FieldHistory {
  value: string | null
  source: FieldSource
  confidence: number
  corrected_by: string | null
  correction_reason: string | null
  created_at: string
}

export interface ExtractedField {
  field: string
  value: string | null
  normalized_value: unknown
  evidence: string | null
  confidence: number
  source: FieldSource
  corrected_by: string | null
  correction_reason: string | null
  /** A human marked this value as incorrect; it must be corrected (or unflagged) first. */
  flagged: boolean
  flag_reason: string | null
  history: FieldHistory[]
}

export interface Issue {
  id: string
  type: IssueType
  severity: Severity
  field: string | null
  message: string
  details: Record<string, unknown>
  status: IssueStatus
  resolution_note: string | null
  created_at: string
}

export interface RiskAssessment {
  agent: string
  urgency: number
  impact: number
  risk_level: RiskLevel
  score: number
  rationale: string
  factors: string[]
  confidence: number
  model: string
  disagreement: boolean
}

export interface Recommendation {
  id: string
  rank: number
  kind: string
  title: string
  description: string
  rationale: string
  estimated_cost_inr: number
  estimated_lead_time_days: number
  risk_reduction: string
  confidence: number
  evidence: string[]
  allocations: { location: string; sku: string; units: number }[]
  requires_approval: boolean
  approval_reasons: string[]
  approvers: Role[]
  status: 'proposed' | 'selected' | 'overridden' | 'rejected' | 'superseded'
  created_by: 'agent' | 'human'
  override_reason: string | null
  model: string
}

export interface Approval {
  id: string
  request_id: string
  request_ref: string
  request_subject: string
  recommendation_id: string
  recommendation_title: string
  approver_role: Role
  kind: 'financial' | 'operational' | 'endorsement'
  approver: { id: string; name: string } | null
  assigned_to: { id: string; name: string } | null
  amount_inr: number
  status: ApprovalStatus
  due_at: string
  decided_at: string | null
  decision_note: string | null
  escalation_level: number
  reasons: string[]
  routing_note: string | null
  /** The Director approved their own request with a written justification. */
  self_approved: boolean
  /** The Director raised this request: they can approve only with a justification. */
  needs_self_override: boolean
  stale: boolean
  stale_reason: string | null
  risk_level: RiskLevel | null
  requested_by: string | null
  can_decide: boolean
  created_at: string
}

export interface Communication {
  id: string
  request_id: string | null
  type: CommType
  to: string[]
  subject: string
  body: string
  status: CommStatus
  attempts: number
  last_error: string | null
  next_retry_at: string | null
  sent_at: string | null
  delivered_via: 'email' | 'in_app' | null
  created_by: 'agent' | 'human'
  edited: boolean
  model: string
  created_at: string
}

export interface CaseEvent {
  id: string
  type: EventType
  payload: Record<string, unknown>
  diff: { changes?: { field: string; old?: unknown; new?: unknown }[] }
  processed: boolean
  created_by: string | null
  created_at: string
}

export interface CaseRef {
  id: string
  ref: string
  status: Status
  subject: string
}

export interface QuarantinedSpan {
  start: number
  end: number
  text: string
  pattern: string
}

export interface AgentTraceEntry {
  agent: string
  ms: number
  model: string
  ok: boolean
  llm_status: string
  error: string | null
}

export interface SubRequest {
  title: string
  text: string
  category: string
}

export interface RequestDetail extends RequestSummary {
  raw_text: string
  sanitized_text: string
  received_at: string
  closed_at: string | null
  previous_status: Status | null
  confidence_breakdown: Partial<Record<'extraction' | 'data' | 'risk' | 'recommendation', number>>
  confidence_band: ConfidenceBand
  degraded_reasons: string[]
  version: number
  injection: { flag?: boolean; patterns?: string[]; quarantined_spans?: QuarantinedSpan[] }
  fields: ExtractedField[]
  missing_fields: string[]
  issues: Issue[]
  risk: Record<'ops' | 'financial' | 'reconciled', RiskAssessment | null>
  recommendations: Recommendation[]
  approvals: Approval[]
  communications: Communication[]
  events: CaseEvent[]
  duplicates: { id: string; ref: string; similarity: number }[]
  duplicate_of: CaseRef | null
  parent: CaseRef | null
  children: CaseRef[]
  sub_requests: SubRequest[]
  agent_trace: AgentTraceEntry[]
  allowed_actions: string[]
}

export interface AuditEntry {
  id: number
  request_id: string | null
  request_ref: string | null
  actor_type: 'agent' | 'human' | 'system'
  actor: string
  action: string
  before: unknown
  after: unknown
  confidence: number | null
  model: string | null
  prompt_hash: string | null
  latency_ms: number | null
  tokens: number | null
  reason: string | null
  ip: string | null
  created_at: string
  hash: string
}

export interface AuditVerify {
  valid: boolean
  rows: number
  broken_at_id: number | null
}

export type HealthState = 'up' | 'down' | 'fallback'
export interface Health {
  status: 'ok' | 'degraded'
  llm: HealthState
  inventory: 'up' | 'down'
  email: 'up' | 'down'
  db: 'up' | 'down'
  llm_mode: string
  model: string
}

export interface Flags {
  llm_down: boolean
  inventory_down: boolean
  email_down: boolean
}

export interface Dashboard {
  total_cases: number
  open_cases: number
  counts_by_status: Partial<Record<Status, number>>
  by_priority: Partial<Record<Priority, number>>
  by_category: Partial<Record<Category, number>>
  overdue: number
  pending_approvals: number
  avg_time_to_close_hours: number
  ai_override_rate: number
  auto_extraction_accuracy: number
  field_correction_rate: Record<string, number>
  degraded_cases: number
  fallback_rate: number
  avg_agent_latency_ms: number
  approval_sla_breaches: number
  critical_cases: {
    id: string
    ref: string
    subject: string
    status: Status
    priority: Priority
    risk_level: RiskLevel | null
  }[]
  pending_approval_items: {
    ref: string
    title: string
    amount_inr: number
    approver_role: Role
    due_at: string
    escalation_level: number
  }[]
}

export interface ManagementSummary {
  markdown: string
  metrics: Dashboard
  generated_at: string
  model: string
  communication_id: string
}

export interface Sample {
  id: string
  label: string
  channel: Channel
  subject: string
  raw_text: string
  sender_email: string | null
  sender_name: string | null
  edge_cases: number[]
}

export interface TickResult {
  reminders: number
  escalations: number
  deadline_alerts: number
  retries: number
  reanalyzed: number
  sla_breaches: number
}

export interface CreateRequestBody {
  channel: Channel
  subject: string
  raw_text: string
  sender_email?: string | null
  sender_name?: string | null
}

export interface Approver {
  id: string
  name: string
  region: string
  approval_limit_inr: number
}
