"""Mock inventory "system of record": a DB table behind the inventory_down fault flag."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, faults
from app.enums import ActorType, Flag
from app.errors import ApiError
from app.models import InventoryItem, Supplier


class InventoryUnavailable(Exception):
    pass


def _rows(db: Session) -> list[InventoryItem]:
    if faults.is_down(db, Flag.INVENTORY_DOWN):
        raise InventoryUnavailable("Inventory system unavailable")
    return list(
        db.scalars(select(InventoryItem).order_by(InventoryItem.sku, InventoryItem.location))
    )


def snapshot(db: Session) -> list[dict[str, Any]] | None:
    """Rows for the agents, or None when the inventory system is down."""
    try:
        rows = _rows(db)
    except InventoryUnavailable:
        return None
    return [
        {
            "sku": r.sku,
            "location": r.location,
            "on_hand": r.on_hand,
            "reserved": r.reserved,
            "free": r.free,
            "updated_at": r.updated_at.isoformat(),
        }
        for r in rows
    ]


def list_items(db: Session) -> list[InventoryItem]:
    try:
        return _rows(db)
    except InventoryUnavailable as exc:
        raise ApiError(503, "SYSTEM_UNAVAILABLE", str(exc)) from exc


def list_suppliers(db: Session) -> list[Supplier]:
    return list(db.scalars(select(Supplier).order_by(Supplier.name)))


def catalog(db: Session) -> dict[str, str]:
    """sku → item name (product master, available even when stock levels are not)."""
    return {
        sku: name
        for sku, name in db.execute(select(InventoryItem.sku, InventoryItem.item_name).distinct())
    }


def _find(db: Session, sku: str, location: str) -> InventoryItem | None:
    return db.scalar(
        select(InventoryItem).where(InventoryItem.sku == sku, InventoryItem.location == location)
    )


def adjust_reservations(
    db: Session,
    allocations: list[dict[str, Any]],
    *,
    release: bool,
    actor: str,
    request_id: str,
) -> None:
    """Reserve (or release) units at source warehouses for an approved transfer."""
    if not allocations:
        return
    sign = -1 if release else 1
    for alloc in allocations:
        row = _find(db, alloc["sku"], alloc["location"])
        if row is not None:
            row.reserved = max(row.reserved + sign * alloc["units"], 0)
    audit.log_event(
        db,
        action="inventory.released" if release else "inventory.reserved",
        actor=actor,
        actor_type=ActorType.SYSTEM,
        request_id=request_id,
        after=allocations,
    )


def set_on_hand(
    db: Session, sku: str, location: str, on_hand: int, actor: str, request_id: str | None
) -> dict[str, Any]:
    row = _find(db, sku, location)
    if row is None:
        raise ApiError(404, "NOT_FOUND", f"No inventory record for {sku} at {location}")
    before = {"sku": sku, "location": location, "on_hand": row.on_hand}
    row.on_hand = on_hand
    audit.log_event(
        db,
        action="inventory.updated",
        actor=actor,
        request_id=request_id,
        before=before,
        after={**before, "on_hand": on_hand},
    )
    return {"old": before["on_hand"], "new": on_hand}
