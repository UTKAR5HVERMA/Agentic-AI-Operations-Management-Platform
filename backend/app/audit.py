"""Append-only, hash-chained audit trail. `log_event` is the ONLY way to write audit rows."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.context import client_ip_var
from app.db import utcnow
from app.enums import ActorType
from app.models import AuditLog, Case

GENESIS_HASH = "0" * 64
# Arbitrary constant key for the Postgres advisory lock that serialises chain appends.
_CHAIN_LOCK_KEY = 7_310_2026

_HASHED_FIELDS = (
    "request_id",
    "actor_type",
    "actor",
    "action",
    "before",
    "after",
    "confidence",
    "model",
    "prompt_hash",
    "latency_ms",
    "tokens",
    "reason",
    "ip",
)


@dataclass(frozen=True)
class AgentMeta:
    """Monitoring data attached to agent audit rows (BACKEND.md §11)."""

    model: str | None = None
    prompt_hash: str | None = None
    latency_ms: int | None = None
    tokens: int | None = None
    confidence: float | None = None


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def compute_hash(row: AuditLog, prev_hash: str) -> str:
    payload = {name: getattr(row, name) for name in _HASHED_FIELDS}
    payload["created_at"] = _iso(row.created_at)
    return hashlib.sha256((_canonical(payload) + prev_hash).encode()).hexdigest()


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")


def _last_hash(db: Session) -> str:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CHAIN_LOCK_KEY})
    last = db.scalar(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1))
    return last or GENESIS_HASH


def log_event(
    db: Session,
    *,
    action: str,
    actor: str,
    actor_type: ActorType = ActorType.HUMAN,
    request_id: str | None = None,
    before: Any = None,
    after: Any = None,
    reason: str | None = None,
    meta: AgentMeta | None = None,
    ip: str | None = None,
) -> AuditLog:
    """Append one audit row to the chain inside the caller's transaction."""
    meta = meta or AgentMeta()
    row = AuditLog(
        request_id=request_id,
        actor_type=str(actor_type),
        actor=actor,
        action=action,
        before=json.loads(_canonical(before)) if before is not None else None,
        after=json.loads(_canonical(after)) if after is not None else None,
        confidence=round(meta.confidence, 4) if meta.confidence is not None else None,
        model=meta.model,
        prompt_hash=meta.prompt_hash,
        latency_ms=meta.latency_ms,
        tokens=meta.tokens,
        reason=reason,
        ip=ip or client_ip_var.get(),
        created_at=utcnow(),
    )
    row.prev_hash = _last_hash(db)
    row.hash = compute_hash(row, row.prev_hash)
    db.add(row)
    db.flush()
    return row


def search(
    db: Session,
    *,
    request_id: str | None = None,
    actor_type: str | None = None,
    actor: str | None = None,
    action: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 500,
) -> list[tuple[AuditLog, str | None]]:
    """Newest-first audit rows with the case reference (read-only)."""
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    for column, value in (
        (AuditLog.request_id, request_id),
        (AuditLog.actor_type, actor_type),
        (AuditLog.actor, actor),
    ):
        if value:
            query = query.where(column == value)
    if action:
        query = query.where(AuditLog.action.startswith(action))
    if since:
        query = query.where(AuditLog.created_at >= since)
    if until:
        query = query.where(AuditLog.created_at <= until)
    rows = list(db.scalars(query))
    ids = {r.request_id for r in rows if r.request_id}
    refs = {cid: ref for cid, ref in db.execute(select(Case.id, Case.ref).where(Case.id.in_(ids)))}
    return [(r, refs.get(r.request_id)) for r in rows]


def verify_chain(db: Session) -> dict[str, Any]:
    """Recompute every hash in order; report the first broken row, if any."""
    prev = GENESIS_HASH
    count = 0
    for row in db.scalars(select(AuditLog).order_by(AuditLog.id)):
        count += 1
        if row.prev_hash != prev or compute_hash(row, prev) != row.hash:
            return {"valid": False, "rows": count, "broken_at_id": row.id}
        prev = row.hash
    return {"valid": True, "rows": count, "broken_at_id": None}
