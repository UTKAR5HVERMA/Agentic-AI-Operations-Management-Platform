"""One test per edge case (DEVELOPMENT_RULES §2.4). Each asserts detect / communicate / recover /
record."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.db import SessionLocal, utcnow
from app.models import Case, Communication
from tests.conftest import (
    ADMIN,
    MANAGER,
    REQUESTER,
    Api,
    audit_actions,
    field,
    issues_of,
)


def test_missing_info(api: Api) -> None:
    case = api.create_sample("missing_info")
    blockers = {i["field"] for i in issues_of(case, "missing_info") if i["severity"] == "blocker"}
    assert {"item", "quantity_required", "location"} <= blockers  # detect
    assert case["status"] == "NEEDS_INFO" and not case["recommendations"]
    draft = next(c for c in case["communications"] if c["type"] == "clarification")
    assert (
        "quantity required" in draft["body"].lower() and draft["status"] == "draft"
    )  # communicate

    res = api.post(
        f"/requests/{case['id']}/provide-info",
        {
            "text": "It is 500 display units for the Pune store launch, delayed by 10 days by "
            "supplier DisplayCo. We need them by 10 Nov."
        },
    )
    assert res.status_code == 200, res.text
    case = res.json()
    assert case["status"] == "PENDING_REVIEW" and case["recommendations"]  # recover
    assert not [i for i in issues_of(case, "missing_info") if i["severity"] == "blocker"]
    assert "validation.missing_fields" in audit_actions(case["id"])  # record


def test_unstated_stock_and_timing_are_flagged(api: Api) -> None:
    """Stock looked up in inventory (never stated) and a delay with no original ETA must be
    surfaced as assumptions, not presented as facts."""
    res = api.post(
        "/requests",
        {
            "channel": "email",
            "subject": "Delay – Mumbai shelving racks",
            "raw_text": "Hi Operations Team, ShelfMart has informed us that the delivery of 300 "
            "shelving racks for the Mumbai store will be delayed by five days. The store refit "
            "requires these racks by 10 Nov. Please assess the impact. Thank you, Mumbai Ops",
            "sender_email": "mumbai.ops@opspilot.demo",
            "sender_name": "Mumbai Ops",
            "received_at": "2026-11-03T10:00:00+05:30",
        },
        as_=REQUESTER,
    )
    assert res.status_code == 201, res.text
    case = api.case(res.json()["id"])  # analysis ran as a background task
    assumed = next(i for i in issues_of(case, "ambiguity") if i["field"] == "quantity_available")
    assert assumed["details"]["inventory_value"] == 150  # detect: Mumbai-WH stock was assumed
    assert "does not say how many units are on hand" in assumed["message"]  # communicate
    assert case["confidence_breakdown"]["data"] == 0.75
    timing = next(
        i for i in issues_of(case, "missing_info") if i["field"] == "original_delivery_date"
    )
    assert timing["severity"] == "warning" and "original delivery date" in timing["message"]
    expedite = next(r for r in case["recommendations"] if r["kind"] == "expedite")
    supplier = expedite["evidence"][0].removeprefix("supplier.")
    assert supplier in expedite["title"]  # title always matches the costed supplier


def test_inventory_conflict(api: Api) -> None:
    case = api.create_sample("happy_path")
    conflict = issues_of(case, "conflict")[0]
    assert conflict["details"]["email_value"] == 120  # detect
    assert conflict["details"]["inventory_value"] == 80
    assert "Email says 120" in conflict["message"]  # communicate
    assert case["confidence_breakdown"]["data"] == 0.7  # system of record used, conf 0.7

    res = api.post(
        f"/requests/{case['id']}/issues/{conflict['id']}/resolve",
        {"resolution": "use_inventory", "note": "Warehouse count is authoritative"},
    )
    assert res.status_code == 200, res.text
    case = res.json()
    available = field(case, "quantity_available")
    assert available["value"] == "80" and available["source"] == "human"  # recover
    assert not issues_of(case, "conflict")
    assert case["confidence_breakdown"]["data"] == 1.0
    actions = audit_actions(case["id"])
    assert {"validation.conflict", "issue.resolved", "field.corrected"} <= set(actions)  # record


def test_duplicate_detection(api: Api) -> None:
    master = api.create_sample("happy_path")
    dup = api.create_sample("duplicate")
    assert dup["duplicates"][0]["ref"] == master["ref"]  # detect
    assert dup["duplicates"][0]["similarity"] >= 0.85
    assert f"Likely duplicate of {master['ref']}" in issues_of(dup, "duplicate")[0]["message"]
    assert dup["status"] == "DUPLICATE" and dup["duplicate_of"]["id"] == master["id"]  # recover
    assert any(c["type"] == "duplicate_notice" for c in dup["communications"])  # communicate
    assert "dedup.linked" in audit_actions(dup["id"])  # record

    res = api.post(f"/requests/{dup['id']}/not-duplicate")
    assert res.status_code == 200, res.text
    restored = res.json()
    assert restored["status"] == "PENDING_REVIEW" and restored["duplicate_of"] is None
    assert "dedup.dismissed" in audit_actions(dup["id"])


def test_multi_issue_handled_in_case(api: Api) -> None:
    case = api.create_sample("multi_issue")
    ambiguity = next(i for i in issues_of(case, "ambiguity") if i["severity"] == "blocker")
    assert len(case["sub_requests"]) == 3  # detect
    assert case["status"] == "NEEDS_INFO" and "split" not in case["allowed_actions"]

    # communicate: the message and the clarification draft list every issue in this one request
    assert "3 separate issues" in ambiguity["message"]
    draft = next(c for c in case["communications"] if c["type"] == "clarification")
    assert all(s["title"] in draft["body"] for s in case["sub_requests"])

    # recover: the Operations Team confirms and the same case continues to analysis
    res = api.post(
        f"/requests/{case['id']}/issues/{ambiguity['id']}/resolve",
        {"resolution": "resolved", "note": "Handle all three in this request"},
    )
    assert res.status_code == 200, res.text
    case = api.case(case["id"])
    assert case["status"] == "PENDING_REVIEW" and not case["children"]
    assert case["recommendations"]
    assert next(i for i in case["issues"] if i["id"] == ambiguity["id"])["status"] == "resolved"
    assert "issue.resolved" in audit_actions(case["id"])  # record


def test_field_correction_reruns_downstream(api: Api) -> None:
    case = api.create_sample("happy_path")
    assert case["recommendations"][0]["title"].startswith("Transfer 420 units")

    # an AI value cannot be edited directly: flag it first
    res = api.patch(
        f"/requests/{case['id']}/fields",
        {"field": "quantity_required", "value": "300", "reason": "Store confirmed 300 units"},
    )
    assert res.status_code == 409 and res.json()["code"] == "FIELD_NOT_FLAGGED"
    res = api.post(
        f"/requests/{case['id']}/fields/flag",
        {"field": "quantity_required", "reason": "Store says 300, not 500"},
    )
    assert res.status_code == 200, res.text
    case = res.json()
    assert field(case, "quantity_required")["flagged"]  # detect: marked as incorrect
    assert issues_of(case, "extraction_flagged")[0]["severity"] == "blocker"
    rec = next(r for r in case["recommendations"] if r["status"] == "proposed")
    blocked = api.post(f"/requests/{case['id']}/recommendations/{rec['id']}/select", {})
    assert blocked.status_code == 409 and blocked.json()["code"] == "FIELD_FLAGGED"

    res = api.patch(
        f"/requests/{case['id']}/fields",
        {
            "field": "quantity_required",
            "value": "300",
            "reason": "Store confirmed 300 units",
            "version": case["version"],
        },
    )
    assert res.status_code == 200, res.text
    case = res.json()
    corrected = field(case, "quantity_required")
    assert corrected["value"] == "300" and corrected["source"] == "human"  # detect
    assert corrected["corrected_by"] and corrected["history"][0]["value"] == "500"  # communicate
    proposed = [r for r in case["recommendations"] if r["status"] == "proposed"]
    assert proposed[0]["title"].startswith("Transfer 220 units")  # recover: re-ran downstream
    assert any(r["status"] == "superseded" for r in case["recommendations"])
    assert not field(case, "quantity_required")["flagged"]  # the correction closes the flag
    assert not issues_of(case, "extraction_flagged")
    assert {"field.flagged", "field.corrected"} <= set(audit_actions(case["id"]))  # record


def test_stale_version_rejected(api: Api) -> None:
    case = api.create_sample("happy_path")
    res = api.patch(
        f"/requests/{case['id']}/fields",
        {
            "field": "quantity_required",
            "value": "300",
            "reason": "Store confirmed",
            "version": case["version"] - 1,
        },
    )
    assert res.status_code == 409 and res.json()["code"] == "STALE_VERSION"


def test_low_confidence_withholds_recommendation(api: Api) -> None:
    case = api.create_sample("low_confidence")
    assert case["overall_confidence"] < 0.5 and case["confidence_band"] == "withheld"  # detect
    low = issues_of(case, "low_confidence")[0]
    assert "Not enough evidence" in low["message"]  # communicate
    assert case["status"] == "NEEDS_INFO" and not case["recommendations"]  # recover
    assert any(c["type"] == "clarification" for c in case["communications"])
    assert "recommendation.withheld" in audit_actions(case["id"])  # record


def test_approval_timeout_escalates(api: Api) -> None:
    case = api.select(api.create_sample("happy_path"))
    approval = case["approvals"][0]
    assert approval["approver_role"] == "ops_manager"

    res = api.post(f"/simulate/approval-timeout/{approval['id']}", as_=ADMIN)
    assert res.status_code == 200, res.text
    escalated = res.json()
    assert escalated["status"] == "escalated" and escalated["escalation_level"] == 1  # detect
    assert escalated["approver_role"] == "admin"  # recover: next level (Director)
    case = api.case(case["id"])
    assert case["status"] == "ESCALATED"
    sent = [c for c in case["communications"] if c["type"] == "escalation"]
    assert sent and sent[0]["status"] == "sent"  # communicate
    assert "approval.escalated" in audit_actions(case["id"])  # record

    res = api.post(f"/approvals/{approval['id']}/approve", {"note": "ok"}, as_=ADMIN)
    assert res.status_code == 200, res.text
    assert api.case(case["id"])["status"] == "IN_PROGRESS"


def test_rejection_reproposes_alternative(api: Api) -> None:
    case = api.create_sample("high_cost")
    top = case["recommendations"][0]
    assert top["kind"] == "expedite" and top["estimated_cost_inr"] > 200_000
    case = api.select(case)
    approval = case["approvals"][0]
    assert approval["approver_role"] == "ops_manager"  # the chosen Regional Manager decides

    res = api.post(
        f"/approvals/{approval['id']}/reject", {"note": "Too expensive this quarter"}, as_=MANAGER
    )
    assert res.status_code == 200, res.text  # detect
    case = api.case(case["id"])
    assert case["status"] == "REJECTED"
    rejected = next(r for r in case["recommendations"] if r["status"] == "rejected")
    assert rejected["kind"] == "expedite"
    decided = next(a for a in case["approvals"] if a["id"] == approval["id"])
    assert decided["decision_note"] == "Too expensive this quarter"  # communicate
    proposed = [r for r in case["recommendations"] if r["status"] == "proposed"]
    assert proposed and all(r["kind"] != "expedite" for r in proposed)
    assert proposed[0]["estimated_cost_inr"] == 0  # next best no-cost option first

    case = api.select(case, rank=proposed[0]["rank"])  # recover: alternative chosen
    assert case["status"] in {"PENDING_APPROVAL", "IN_PROGRESS"}
    actions = audit_actions(case["id"])
    assert {"approval.rejected", "recommendation.reproposed"} <= set(actions)  # record


def test_supplier_revision_reassesses(api: Api) -> None:
    case = api.select(api.create_sample("happy_path"))
    approval = case["approvals"][0]

    res = api.post(
        f"/requests/{case['id']}/events",
        {"type": "supplier_date_revised", "payload": {"new_delay_days": 4}},
    )
    assert res.status_code == 200, res.text
    case = res.json()
    assert field(case, "delay_days")["value"] == "4"  # detect
    assert field(case, "delay_days")["source"] == "event"
    changed = issues_of(case, "circumstances_changed")[0]
    assert "10 → 4" in changed["message"]  # communicate
    assert case["events"][0]["diff"]["changes"][0]["old"] == "10"
    assert case["status"] == "PENDING_APPROVAL" and case["approvals"][0]["stale"]  # recover

    stale = api.post(f"/approvals/{approval['id']}/approve", {}, as_=MANAGER)
    assert stale.status_code == 409 and stale.json()["code"] == "STALE_APPROVAL"
    ok = api.post(f"/approvals/{approval['id']}/approve", {"reconfirm": True}, as_=MANAGER)
    assert ok.status_code == 200, ok.text
    assert {"event.processed", "approval.marked_stale"} <= set(audit_actions(case["id"]))


def test_llm_down_uses_fallback(api: Api) -> None:
    assert api.put("/admin/flags", {"llm_down": True}).json()["llm_down"] is True
    assert api.client.get("/api/health").json()["llm"] == "down"  # detect

    case = api.create_sample("happy_path")
    assert case["degraded"] and case["degraded_reasons"] == ["llm"]  # communicate
    assert issues_of(case, "system_unavailable")
    assert case["status"] == "PENDING_REVIEW" and case["recommendations"]  # still works
    assert all(not t["ok"] for t in case["agent_trace"] if t["llm_status"] == "unavailable")

    api.put("/admin/flags", {"llm_down": False})
    tick = api.post("/simulate/scheduler-tick", as_=ADMIN).json()
    assert tick["reanalyzed"] == 1  # recover
    case = api.case(case["id"])
    assert not case["degraded"] and not issues_of(case, "system_unavailable")
    assert "system.unavailable" in audit_actions()  # record


def test_inventory_down_uses_email_value(api: Api) -> None:
    api.put("/admin/flags", {"inventory_down": True})
    case = api.create_sample("happy_path")
    assert case["degraded_reasons"] == ["inventory"]
    assert issues_of(case, "system_unavailable")[0]["details"]["system"] == "inventory"
    assert case["confidence_breakdown"]["data"] == 0.5
    assert field(case, "quantity_available")["confidence"] == 0.5
    assert api.get("/inventory").status_code == 503


def test_prompt_injection_quarantined(api: Api) -> None:
    case = api.create_sample("prompt_injection")
    assert case["injection_flag"] and case["injection"]["quarantined_spans"]  # detect
    assert "Suspicious instructions" in issues_of(case, "injection")[0]["message"]  # communicate
    assert "IGNORE ALL PREVIOUS" not in case["sanitized_text"]  # recover: analysed sanitized text
    assert "vendor-deals@freemail.com" not in case["sanitized_text"]
    assert case["status"] == "PENDING_REVIEW" and not case["approvals"]  # nothing approved
    assert all(
        "freemail" not in c["body"] and "freemail" not in " ".join(c["to"])
        for c in case["communications"]
    )
    assert all(r["requires_approval"] for r in case["recommendations"])
    assert any(
        "suspicious" in reason for r in case["recommendations"] for reason in r["approval_reasons"]
    )
    assert "security.injection_detected" in audit_actions(case["id"])  # record


def test_comm_failure_retries(api: Api) -> None:
    case = api.create_sample("happy_path")
    draft = next(c for c in case["communications"] if c["type"] == "stakeholder_update")
    api.put("/admin/flags", {"email_down": True})

    first = api.post(f"/communications/{draft['id']}/send").json()
    assert first["status"] == "failed" and first["attempts"] == 1  # detect
    assert first["next_retry_at"] and "unavailable" in first["last_error"]
    # communicate: the team is alerted on the FIRST failure, not after the retries run out
    alert = issues_of(api.case(case["id"]), "communication_failure")
    assert len(alert) == 1 and "attempt 1/3" in alert[0]["message"]

    for _ in range(2):  # scheduler retries with backoff (made due immediately here)
        with SessionLocal() as db:
            comm = db.scalar(select(Communication).where(Communication.id == draft["id"]))
            comm.next_retry_at = utcnow() - timedelta(seconds=1)
            db.commit()
        assert api.post("/simulate/scheduler-tick", as_=ADMIN).json()["retries"] == 1
    case = api.case(case["id"])
    comm = next(c for c in case["communications"] if c["id"] == draft["id"])
    assert comm["attempts"] == 3 and comm["delivered_via"] == "in_app"  # recover: fallback
    alert = issues_of(case, "communication_failure")
    assert len(alert) == 1 and "posted in-app" in alert[0]["message"]

    api.put("/admin/flags", {"email_down": False})
    manual = api.post(f"/communications/{draft['id']}/send").json()
    assert manual["status"] == "sent"  # manual retry once the service is back
    issue = next(i for i in api.case(case["id"])["issues"] if i["id"] == alert[0]["id"])
    assert issue["status"] == "resolved"  # the alert closes itself on delivery
    assert {"comm.failed", "comm.retry", "comm.fallback_channel", "comm.sent"} <= set(
        audit_actions(case["id"])
    )  # record


def test_agent_disagreement(api: Api) -> None:
    case = api.create_sample("happy_path")
    ops, fin = case["risk"]["ops"], case["risk"]["financial"]
    assert (ops["risk_level"], fin["risk_level"]) == ("critical", "medium")  # detect
    assert "Agents disagree" in issues_of(case, "agent_disagreement")[0]["message"]
    reconciled = case["risk"]["reconciled"]
    assert reconciled["risk_level"] == "critical" and reconciled["disagreement"]  # recover
    assert case["confidence_breakdown"]["risk"] == 0.5
    assert "Risk agents disagree" in case["recommendations"][0]["approval_reasons"]
    assert "risk.disagreement" in audit_actions(case["id"])  # record


def test_cancel_cancels_pending_approvals(api: Api) -> None:
    case = api.select(api.create_sample("happy_path"))
    assert case["approvals"][0]["status"] == "pending"

    res = api.post(f"/requests/{case['id']}/cancel", {"reason": "Store launch postponed"})
    assert res.status_code == 200, res.text
    case = res.json()
    assert case["status"] == "CANCELLED"  # detect + recover
    assert all(a["status"] == "cancelled" for a in case["approvals"])
    notices = [c for c in case["communications"] if c["type"] == "cancellation"]
    assert any(c["status"] == "sent" for c in notices)  # approvers notified
    assert any(c["status"] == "draft" for c in notices)  # communicate: notice to sender
    assert {"approval.cancelled", "request.cancelled"} <= set(audit_actions(case["id"]))


def test_launch_postponed_after_approval_needs_manager(api: Api) -> None:
    case = api.select(api.create_sample("happy_path"))
    api.post(f"/approvals/{case['approvals'][0]['id']}/approve", {}, as_=MANAGER)

    res = api.post(
        f"/requests/{case['id']}/events",
        {"type": "launch_postponed", "payload": {"reason": "Mall opening moved"}},
    )
    assert res.status_code == 200, res.text
    case = res.json()
    assert case["status"] == "ON_HOLD"  # approved spend: the Operations Team cannot cancel it
    assert issues_of(case, "circumstances_changed")[0]["severity"] == "blocker"

    res = api.post(
        f"/requests/{case['id']}/cancel", {"reason": "Launch moved to next month"}, as_=MANAGER
    )
    assert res.status_code == 200, res.text
    stock = {(r["sku"], r["location"]): r for r in api.get("/inventory").json()}
    assert stock[("DU-500", "Mumbai-WH")]["reserved"] == 0  # reserved stock released
    assert "inventory.released" in audit_actions(case["id"])


def test_provider_failure_recovery_backs_off(api: Api) -> None:
    case = api.create_sample("happy_path")
    with SessionLocal() as db:
        row = db.get(Case, case["id"])
        row.degraded, row.degraded_reasons = True, ["llm"]
        row.agent_trace = [{"agent": "extraction", "error": "provider error"}]
        db.commit()
    assert api.post("/simulate/scheduler-tick", as_=ADMIN).json()["reanalyzed"] == 0


def test_submit_returns_immediately_then_analyses(api: Api) -> None:
    from tests.conftest import RECEIVED_AT, REQUESTER

    body = {
        "subject": "Display units late",
        "raw_text": "500 display units for Pune delayed.",
        "received_at": RECEIVED_AT,
    }
    res = api.post("/requests", body, as_=REQUESTER)
    assert res.status_code == 201 and res.json()["status"] == "NEW"
    assert not res.json()["recommendations"]  # nothing analysed in the submit response
    assert api.case(res.json()["id"], as_=REQUESTER)["status"] != "NEW"


def test_scheduler_picks_up_unanalysed_cases(api: Api) -> None:
    from app.schemas import CreateRequest
    from app.services.cases import create_case

    with SessionLocal() as db:
        case = create_case(db, CreateRequest(subject="Stuck", raw_text="300 racks for Pune"), None)
        case.created_at = utcnow() - timedelta(minutes=5)
        db.commit()
        case_id = case.id
    assert api.post("/simulate/scheduler-tick", as_=ADMIN).json()["reanalyzed"] >= 1
    assert api.case(case_id, as_=ADMIN)["status"] != "NEW"


def test_flag_can_be_removed_when_value_is_right(api: Api) -> None:
    case = api.create_sample("happy_path")
    res = api.post(
        f"/requests/{case['id']}/fields/flag",
        {"field": "location", "reason": "Looks like Mumbai, checking"},
    )
    flag = issues_of(res.json(), "extraction_flagged")[0]
    res = api.post(
        f"/requests/{case['id']}/issues/{flag['id']}/resolve",
        {"resolution": "dismiss", "note": "Pune is right after all"},
    )
    assert res.status_code == 200, res.text
    assert not field(res.json(), "location")["flagged"]
    assert field(res.json(), "location")["source"] != "human"  # value unchanged
    assert api.select(api.case(case["id"]))["status"] == "PENDING_APPROVAL"  # unblocked
