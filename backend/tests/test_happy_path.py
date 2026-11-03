"""R1–R10 end to end: sample 1 → extraction → risk → recommendation → approval → closure."""

from __future__ import annotations

from tests.conftest import MANAGER, Api, audit_actions, field, issues_of


def test_happy_path(api: Api) -> None:
    case = api.create_sample("happy_path")

    # R2: extraction with evidence
    assert case["status"] == "PENDING_REVIEW"
    assert case["ref"].startswith("OPS-2026-")
    assert field(case, "quantity_required")["normalized_value"] == 500
    assert field(case, "quantity_required")["evidence"] == "500 display units"
    assert field(case, "location")["normalized_value"] == "Pune"
    assert field(case, "delay_days")["normalized_value"] == 10
    assert field(case, "quantity_available")["normalized_value"] == 120
    assert field(case, "approval_deadline")["value"] == "4:00 PM today"
    assert field(case, "event")["value"] == "store launch"
    assert all(f["evidence"] for f in case["fields"])

    # R3: three risk assessments with rationale; R5: 2–4 costed options incl. a zero-cost one
    assert {"ops", "financial", "reconciled"} <= {k for k, v in case["risk"].items() if v}
    assert case["risk"]["reconciled"]["rationale"]
    recs = case["recommendations"]
    assert 2 <= len(recs) <= 4
    assert any(r["estimated_cost_inr"] == 0 for r in recs)
    top = recs[0]
    assert top["kind"] == "transfer" and top["estimated_cost_inr"] == 42_000
    assert top["evidence"] and top["rationale"]
    assert top["approvers"] == ["ops_manager"]
    assert case["agent_trace"] and case["communications"][0]["status"] == "draft"
    assert "select_recommendation" in case["allowed_actions"]

    # R6: routing per §9 — ₹42,000 → ops_manager
    case = api.select(case)
    assert case["status"] == "PENDING_APPROVAL"
    approval = case["approvals"][0]
    assert approval["approver_role"] == "ops_manager" and approval["amount_inr"] == 42_000

    res = api.post(f"/approvals/{approval['id']}/approve", {"note": "Go ahead"}, as_=MANAGER)
    assert res.status_code == 200, res.text
    case = api.case(case["id"])
    assert case["status"] == "IN_PROGRESS"

    # R8: tracked to closure via allowed transitions only
    for target in ("RESOLVED", "CLOSED"):
        res = api.post(f"/requests/{case['id']}/transition", {"to": target, "reason": "done"})
        assert res.status_code == 200, res.text
    case = api.case(case["id"])
    assert case["status"] == "CLOSED" and case["closed_at"]
    assert any(c["type"] == "closure" for c in case["communications"])

    # R4: the 120 vs 80 conflict was surfaced; R10: audit trail is complete and valid
    assert issues_of(case, "conflict")
    actions = audit_actions(case["id"])
    for expected in (
        "request.created",
        "extraction.completed",
        "risk.reconciled",
        "recommendation.generated",
        "recommendation.selected",
        "approval.requested",
        "approval.approved",
        "inventory.reserved",
    ):
        assert expected in actions, expected
    verify = api.get("/audit/verify").json()
    assert verify["valid"] is True and verify["rows"] > 20


def test_approved_transfer_reserves_stock(api: Api) -> None:
    case = api.select(api.create_sample("happy_path"))
    api.post(f"/approvals/{case['approvals'][0]['id']}/approve", {}, as_=MANAGER)
    stock = {(r["sku"], r["location"]): r for r in api.get("/inventory").json()}
    assert stock[("DU-500", "Mumbai-WH")]["reserved"] == 260
    assert stock[("DU-500", "Ahmedabad-WH")]["reserved"] == 150


def test_samples_and_reference_data(api: Api) -> None:
    assert len(api.get("/samples").json()) == 8
    assert len(api.get("/suppliers").json()) >= 3
    health = api.client.get("/api/health").json()
    assert health["db"] == "up" and health["llm"] == "fallback"
