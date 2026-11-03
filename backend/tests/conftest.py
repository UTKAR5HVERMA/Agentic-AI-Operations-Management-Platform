"""Test fixtures: mock LLM mode, a fresh SQLite database per test, helpers to act as demo users."""

from __future__ import annotations

import os

os.environ.update(
    LLM_MODE="mock",
    LLM_API_KEY="",
    SCHEDULER_ENABLED="false",
    SEED_ON_STARTUP="true",
    JWT_SECRET="test-secret-0123456789abcdef0123456789abcdef",
    WEBHOOK_SECRET="test-webhook-secret",
    LOG_LEVEL="WARNING",
)

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import create_access_token
from app.config import get_settings
from app.db import SessionLocal, configure_engine
from app.main import app
from app.models import AuditLog, User
from app.seed import SAMPLES

get_settings.cache_clear()

# Fixed past receipt time: every relative deadline in the samples has already passed, so risk
# scoring does not depend on the wall clock.
RECEIVED_AT = "2026-10-01T10:00:00+05:30"
OPS_TEAM = "ops.team@opspilot.demo"  # ops_analyst: does the case work
MANAGER = "manager@opspilot.demo"
MANAGER_NORTH = "manager.north@opspilot.demo"
ADMIN = "admin@opspilot.demo"
REQUESTER = "requester@opspilot.demo"


class Api:
    """Thin helper over TestClient that authenticates as demo users."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self._tokens: dict[str, str] = {}

    def headers(self, email: str) -> dict[str, str]:
        if email not in self._tokens:
            with SessionLocal() as db:
                user = db.scalar(select(User).where(User.email == email))
                assert user is not None, email
                self._tokens[email] = create_access_token(user)
        return {"Authorization": f"Bearer {self._tokens[email]}"}

    def get(self, path: str, as_: str = OPS_TEAM, **kw: Any) -> Any:
        return self.client.get(f"/api{path}", headers=self.headers(as_), **kw)

    def post(self, path: str, json: Any = None, as_: str = OPS_TEAM) -> Any:
        return self.client.post(f"/api{path}", json=json or {}, headers=self.headers(as_))

    def patch(self, path: str, json: Any, as_: str = OPS_TEAM) -> Any:
        return self.client.patch(f"/api{path}", json=json, headers=self.headers(as_))

    def put(self, path: str, json: Any, as_: str = ADMIN) -> Any:
        return self.client.put(f"/api{path}", json=json, headers=self.headers(as_))

    def create_sample(
        self, sample_id: str, as_: str = OPS_TEAM, submit_as: str = REQUESTER, **overrides: Any
    ) -> dict:
        """Submit via the request desk (as in the demo), then work it `as_`."""
        sample = next(s for s in SAMPLES if s["id"] == sample_id)
        body = {
            k: sample[k] for k in ("channel", "subject", "raw_text", "sender_email", "sender_name")
        }
        body.update(received_at=RECEIVED_AT, **overrides)
        res = self.post("/requests", body, as_=submit_as)
        assert res.status_code == 201, res.text
        assert res.json()["status"] == "NEW"  # analysis runs in the background
        # TestClient runs background tasks before returning, so the case is analysed by now.
        return self.case(res.json()["id"], as_=as_)

    def case(self, case_id: str, as_: str = OPS_TEAM) -> dict:
        res = self.get(f"/requests/{case_id}", as_=as_)
        assert res.status_code == 200, res.text
        return res.json()

    def select(self, case: dict, rank: int = 1, as_: str = OPS_TEAM) -> dict:
        rec = next(
            r for r in case["recommendations"] if r["rank"] == rank and r["status"] == "proposed"
        )
        res = self.post(f"/requests/{case['id']}/recommendations/{rec['id']}/select", {}, as_=as_)
        assert res.status_code == 200, res.text
        return res.json()


@pytest.fixture
def client(tmp_path: Any) -> Iterator[TestClient]:
    configure_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with TestClient(app) as c:
        yield c


@pytest.fixture
def api(client: TestClient) -> Api:
    return Api(client)


@pytest.fixture
def db(client: TestClient) -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def audit_actions(request_id: str | None = None) -> list[str]:
    with SessionLocal() as db:
        query = select(AuditLog.action).order_by(AuditLog.id)
        if request_id:
            query = query.where(AuditLog.request_id == request_id)
        return list(db.scalars(query))


def issues_of(case: dict, type_: str, status: str = "open") -> list[dict]:
    return [i for i in case["issues"] if i["type"] == type_ and i["status"] == status]


def field(case: dict, name: str) -> dict | None:
    return next((f for f in case["fields"] if f["field"] == name), None)
