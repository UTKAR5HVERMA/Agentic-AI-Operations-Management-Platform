"""Demo accounts added after a database was first seeded still appear on startup."""

from __future__ import annotations

from sqlalchemy import delete, select, text

from app.db import SessionLocal, add_missing_columns, get_engine
from app.models import User
from app.seed import sync_demo_users
from tests.conftest import OPS_TEAM, Api, audit_actions


def test_new_nullable_column_is_added_to_existing_db(api: Api) -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE approvals DROP COLUMN routing_note"))
    assert add_missing_columns(engine) == ["approvals.routing_note"]
    assert add_missing_columns(engine) == []  # idempotent


def test_sync_adds_missing_demo_user(api: Api) -> None:
    with SessionLocal() as db:
        db.execute(delete(User).where(User.email == OPS_TEAM))
        db.commit()
        assert sync_demo_users(db) == [OPS_TEAM]
        assert db.scalar(select(User.role).where(User.email == OPS_TEAM)) == "ops_analyst"
        assert sync_demo_users(db) == []  # idempotent

    res = api.client.post("/api/auth/login", json={"email": OPS_TEAM, "password": "Demo@123"})
    assert res.status_code == 200, res.text
    assert "system.demo_users_synced" in audit_actions()
