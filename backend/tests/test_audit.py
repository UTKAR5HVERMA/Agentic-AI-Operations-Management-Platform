"""Audit trail: mutations recorded, agent rows carry monitoring data, chain tamper-evident."""

from __future__ import annotations

from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import AuditLog
from tests.conftest import MANAGER, Api, audit_actions


def test_every_mutation_writes_audit(api: Api) -> None:
    case = api.create_sample("happy_path")
    steps = [
        lambda: api.post(
            f"/requests/{case['id']}/fields/flag",
            {"field": "delay_days", "reason": "Supplier said 12"},
        ),
        lambda: api.patch(
            f"/requests/{case['id']}/fields",
            {"field": "delay_days", "value": "12", "reason": "Supplier call"},
        ),
        lambda: api.select(api.case(case["id"])),
    ]
    for step in steps:
        before = len(audit_actions())
        step()
        assert len(audit_actions()) > before


def test_agent_rows_carry_monitoring_data(api: Api) -> None:
    case = api.create_sample("happy_path")
    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(AuditLog).where(
                    AuditLog.request_id == case["id"], AuditLog.action == "extraction.completed"
                )
            )
        )
    assert rows and rows[0].actor_type == "agent"
    assert rows[0].model == "fallback" and len(rows[0].prompt_hash) == 64
    assert rows[0].latency_ms is not None


def test_chain_verifies_and_detects_tampering(api: Api) -> None:
    case = api.select(api.create_sample("happy_path"))
    api.post(f"/approvals/{case['approvals'][0]['id']}/approve", {}, as_=MANAGER)
    assert api.get("/audit/verify").json()["valid"] is True

    with SessionLocal() as db:
        target = db.scalar(select(AuditLog.id).where(AuditLog.action == "approval.approved"))
        db.execute(text("UPDATE audit_log SET reason = 'edited' WHERE id = :id"), {"id": target})
        db.commit()
    result = api.get("/audit/verify").json()
    assert result["valid"] is False and result["broken_at_id"] == target


def test_audit_filters_and_refs(api: Api) -> None:
    case = api.create_sample("happy_path")
    rows = api.get("/audit", params={"request_id": case["id"], "actor_type": "agent"}).json()
    assert rows and all(r["actor_type"] == "agent" for r in rows)
    assert all(r["request_ref"] == case["ref"] for r in rows)
    assert {r["action"] for r in rows} >= {"extraction.completed", "risk.reconciled"}


def test_no_update_or_delete_routes_for_audit(api: Api) -> None:
    for method in ("put", "patch", "delete"):
        res = getattr(api.client, method)("/api/audit/1", headers=api.headers(MANAGER))
        assert res.status_code in {404, 405}
