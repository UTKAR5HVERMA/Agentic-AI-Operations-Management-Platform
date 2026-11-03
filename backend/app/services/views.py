"""ORM → API schema mapping (BACKEND.md §8). Routers return only these schemas."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import rbac
from app.agents.confidence import band
from app.agents.validation import required_fields
from app.config import get_settings
from app.enums import IN_FLIGHT_APPROVALS, CommStatus, IssueStatus, IssueType, RiskAgentName
from app.models import Approval, Case, ExtractedField, User
from app.schemas import (
    ApprovalOut,
    CaseRef,
    CommunicationOut,
    DuplicateOut,
    EventOut,
    ExtractedFieldOut,
    FieldHistory,
    IssueOut,
    RecommendationOut,
    RequestDetail,
    RequestSummary,
    RiskOut,
    Sender,
    UserRef,
)


def _risk_level(case: Case) -> str | None:
    reconciled = next(
        (r for r in case.risk_assessments if r.is_current and r.agent == RiskAgentName.RECONCILED),
        None,
    )
    return reconciled.risk_level if reconciled else None


def summary(case: Case) -> RequestSummary:
    return RequestSummary(**_summary_fields(case))


def _summary_fields(case: Case) -> dict[str, object]:
    return {
        "id": case.id,
        "ref": case.ref,
        "subject": case.subject,
        "status": case.status,
        "priority": case.priority,
        "category": case.category,
        "channel": case.channel,
        "sender": Sender(name=case.sender_name, email=case.sender_email),
        "region": case.region,
        "risk_level": _risk_level(case),
        "overall_confidence": case.overall_confidence,
        "degraded": case.degraded,
        "injection_flag": case.injection_flag,
        "open_issues": sum(i.status == IssueStatus.OPEN for i in case.issues),
        "pending_approvals": sum(a.status in IN_FLIGHT_APPROVALS for a in case.approvals),
        "awaiting_role": next(
            (a.approver_role for a in case.approvals if a.status in IN_FLIGHT_APPROVALS), None
        ),
        "deadline_at": case.deadline_at,
        "sla_due_at": case.sla_due_at,
        "created_at": case.created_at,
        "updated_at": case.updated_at,
    }


def _fields(case: Case) -> list[ExtractedFieldOut]:
    by_field: dict[str, list[ExtractedField]] = defaultdict(list)
    for row in case.fields:
        by_field[row.field].append(row)
    flags = {
        i.field: (i.details or {}).get("reason")
        for i in case.issues
        if i.type == IssueType.EXTRACTION_FLAGGED and i.status == IssueStatus.OPEN
    }
    out = []
    for name, rows in by_field.items():
        current = next((r for r in rows if r.is_current), None)
        if current is None:
            continue
        out.append(
            ExtractedFieldOut(
                field=name,
                value=current.value,
                normalized_value=current.normalized_value,
                evidence=current.evidence,
                confidence=current.confidence,
                source=current.source,
                corrected_by=current.corrected_by.name if current.corrected_by else None,
                correction_reason=current.correction_reason,
                flagged=name in flags,
                flag_reason=flags.get(name),
                history=[
                    FieldHistory(
                        value=r.value,
                        source=r.source,
                        confidence=r.confidence,
                        corrected_by=r.corrected_by.name if r.corrected_by else None,
                        correction_reason=r.correction_reason,
                        created_at=r.created_at,
                    )
                    for r in rows
                    if not r.is_current
                ],
            )
        )
    return out


def approval(a: Approval, user: User) -> ApprovalOut:
    case = a.case
    return ApprovalOut(
        id=a.id,
        request_id=case.id,
        request_ref=case.ref,
        request_subject=case.subject,
        recommendation_id=a.recommendation_id,
        recommendation_title=a.recommendation.title,
        approver_role=a.approver_role,
        kind=a.kind,
        approver=UserRef(id=a.approver.id, name=a.approver.name) if a.approver else None,
        assigned_to=UserRef(id=a.assigned_to.id, name=a.assigned_to.name)
        if a.assigned_to
        else None,
        amount_inr=a.amount_inr,
        status=a.status,
        due_at=a.due_at,
        decided_at=a.decided_at,
        decision_note=a.decision_note,
        escalation_level=a.escalation_level,
        reasons=a.reasons,
        routing_note=a.routing_note,
        self_approved=bool(a.self_approved),
        needs_self_override=rbac.needs_self_override(user, a, case),
        advice=a.advice,
        stale=a.stale,
        stale_reason=a.stale_reason,
        risk_level=_risk_level(case),
        requested_by=case.sender_name or case.sender_email,
        can_decide=rbac.can_decide(user, a, case),
        created_at=a.created_at,
    )


def _case_ref(case: Case | None) -> CaseRef | None:
    if case is None:
        return None
    return CaseRef(id=case.id, ref=case.ref, status=case.status, subject=case.subject)


def detail(db: Session, case: Case, user: User) -> RequestDetail:
    settings = get_settings()
    current = {f.field for f in case.fields if f.is_current}
    risks = {r.agent: r for r in case.risk_assessments if r.is_current}

    def risk(agent: RiskAgentName) -> RiskOut | None:
        r = risks.get(str(agent))
        if r is None:
            return None
        return RiskOut(
            agent=r.agent,
            urgency=r.urgency,
            impact=r.impact,
            risk_level=r.risk_level,
            score=r.score,
            rationale=r.rationale,
            factors=r.factors,
            confidence=r.confidence,
            model=r.model,
            disagreement=bool(r.details.get("disagreement")),
        )

    children = list(db.scalars(select(Case).where(Case.parent_id == case.id)))
    return RequestDetail(
        **_summary_fields(case),
        raw_text=case.raw_text,
        sanitized_text=case.sanitized_text,
        received_at=case.received_at,
        previous_status=case.previous_status,
        closed_at=case.closed_at,
        confidence_breakdown=case.confidence_breakdown,
        confidence_band=band(
            case.overall_confidence,
            settings.confidence_auto_threshold,
            settings.confidence_block_threshold,
        ),
        degraded_reasons=case.degraded_reasons,
        version=case.version,
        injection=case.injection_details
        or {"flag": False, "patterns": [], "quarantined_spans": []},
        fields=_fields(case),
        missing_fields=[f for f in required_fields(case.category) if f not in current],
        issues=[IssueOut.model_validate(i) for i in case.issues],
        risk={
            "ops": risk(RiskAgentName.OPS),
            "financial": risk(RiskAgentName.FINANCIAL),
            "reconciled": risk(RiskAgentName.RECONCILED),
        },
        recommendations=[
            RecommendationOut.model_validate(r)
            for r in sorted(
                case.recommendations,
                key=lambda r: (r.status != "selected", r.status != "proposed", r.rank),
            )
        ],
        approvals=[approval(a, user) for a in case.approvals],
        communications=[
            CommunicationOut.model_validate(c)
            for c in case.communications
            if c.status != CommStatus.DISCARDED
        ],
        events=[EventOut.model_validate(e) for e in case.events],
        duplicates=[DuplicateOut(**d) for d in case.duplicate_candidates],
        duplicate_of=_case_ref(
            db.get(Case, case.duplicate_of_id) if case.duplicate_of_id else None
        ),
        parent=_case_ref(db.get(Case, case.parent_id) if case.parent_id else None),
        children=[c for c in (_case_ref(ch) for ch in children) if c],
        sub_requests=case.sub_requests,
        agent_trace=case.agent_trace,
        allowed_actions=rbac.allowed_actions(user, case),
    )
