"""A4: the AI advises the approver (approve / reject / forward) — it never decides — and every
AI-written approval email and report keeps only numbers that are in the facts."""

from __future__ import annotations

from app.agents import approval_advice, communication, reporting
from app.enums import CommType
from tests.conftest import ADMIN, MANAGER, Api, audit_actions
from tests.test_composer import _llm_returning

FACTS = {
    "ref": "OPS-2026-0001",
    "option": "Transfer 420 units from Mumbai-WH",
    "amount_inr": 42_000,
    "lead_time_days": 2,
    "reasons": ["Additional cost ₹42,000"],
    "alternatives": [{"title": "Express order", "cost_inr": 90_000, "lead_time_days": 3}],
    "approver_role": "ops_manager",
    "approver_limit_inr": 50_000,
}


def test_advice_is_stored_shown_and_audited(api: Api) -> None:
    case = api.select(api.create_sample("high_cost"))
    approval = case["approvals"][0]
    advice = approval["advice"]
    assert advice["suggestion"] == "forward"  # above the manager's ₹50,000 limit
    assert "limit" in advice["rationale"] and advice["model"] == "rule-based"
    email = next(c for c in case["communications"] if c["type"] == "approval_request")
    assert "AI suggestion (advice only, the decision is yours)" in email["body"]
    assert "approval.advice" in audit_actions(case["id"])
    assert approval["status"] == "pending"  # advice never decides

    res = api.post(f"/approvals/{approval['id']}/escalate", {"note": "Above my limit"}, as_=MANAGER)
    assert res.status_code == 200, res.text
    director = api.case(case["id"], as_=ADMIN)["approvals"][0]
    assert director["approver_role"] == "admin"
    assert director["advice"]["suggestion"] in {"approve", "reject"}  # nobody above the Director
    escalation = next(
        c for c in api.case(case["id"])["communications"] if c["type"] == "escalation"
    )
    assert "forwarded to you by the Regional Manager: Above my limit" in escalation["body"]


def test_rules_suggest_rejecting_a_dearer_option() -> None:
    facts = {
        **FACTS,
        "amount_inr": 90_000,
        "lead_time_days": 3,
        "approver_role": "admin",
        "alternatives": [{"title": "Transfer", "cost_inr": 42_000, "lead_time_days": 2}],
    }
    advice = approval_advice.rule_advice(facts)
    assert advice["suggestion"] == "reject" and "Transfer" in advice["rationale"]
    assert approval_advice.rule_advice(FACTS)["suggestion"] == "approve"


def test_llm_advice_is_used_when_grounded() -> None:
    llm = _llm_returning(
        '{"suggestion": "approve", "rationale": "Transfer covers the need for ₹42,000 in 2 days.",'
        ' "checks": ["Confirm Mumbai-WH can release the stock"]}'
    )
    advice, _ = approval_advice.advise(FACTS, llm)
    assert advice["suggestion"] == "approve" and advice["model"] != "rule-based"


def test_llm_advice_with_invented_numbers_or_forbidden_choice_falls_back() -> None:
    invented = _llm_returning(
        '{"suggestion": "approve", "rationale": "It saves ₹75,000 compared with last month."}'
    )
    assert approval_advice.advise(FACTS, invented)[0]["model"] == "rule-based"
    over_limit = {**FACTS, "amount_inr": 90_000}
    approve = _llm_returning('{"suggestion": "approve", "rationale": "Approve it, it is urgent."}')
    advice, _ = approval_advice.advise(over_limit, approve)
    assert advice["suggestion"] == "forward"  # a manager cannot approve above the limit


def test_ai_approval_email_keeps_the_original_verbatim_and_checks_numbers() -> None:
    facts = {
        "ref": "OPS-2026-0001",
        "recommendation": "Transfer 420 units",
        "amount_inr": 42_000,
        "routing_note": "Please decide today",
        "original_text": "We need 500 units",
        "original_from": "Store",
    }
    good = _llm_returning(
        '{"subject": "Approval needed: Transfer 420 units", "body": "Please approve ₹42,000."}'
    )
    d, _ = communication.draft(CommType.APPROVAL_REQUEST, facts, ["m@x"], good)
    assert d["model"] != "template" and d["body"].startswith("Please approve ₹42,000.")
    assert "Please decide today" in d["body"] and "> We need 500 units" in d["body"]

    bad = _llm_returning('{"subject": "Approval", "body": "Approve ₹99,000 by Friday."}')
    d, _ = communication.draft(CommType.APPROVAL_REQUEST, facts, ["m@x"], bad)
    assert d["model"] == "template"


def test_report_with_invented_numbers_uses_the_template() -> None:
    metrics = {
        "open_cases": 4,
        "pending_approvals": 1,
        "overdue": 0,
        "degraded_cases": 0,
        "critical_cases": [],
        "pending_approval_items": [],
        "ai_override_rate": 0.25,
        "auto_extraction_accuracy": 0.9,
        "fallback_rate": 0.0,
        "approval_sla_breaches": 0,
        "counts_by_status": {},
    }
    ok = _llm_returning('{"markdown": "## Headline\\n4 open cases, 25% overridden."}')
    assert reporting.summarize(metrics, ok)[2] is True
    invented = _llm_returning('{"markdown": "## Headline\\n12 open cases."}')
    markdown, _, used_llm = reporting.summarize(metrics, invented)
    assert used_llm is False and markdown.startswith("## Headline\n4 open cases")
