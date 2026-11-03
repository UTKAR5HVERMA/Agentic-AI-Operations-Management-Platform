from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import faults
from app.auth import get_current_user
from app.db import get_db
from app.enums import Role
from app.models import User
from app.rbac import require_role
from app.schemas import Flags, FlagsUpdate, Health, InventoryOut, Sample, SupplierOut
from app.seed import SAMPLES
from app.services import admin, inventory

router = APIRouter(tags=["admin"])
admin_only = require_role(Role.ADMIN)


@router.get("/health", response_model=Health)
def health(db: Session = Depends(get_db)) -> Health:
    return Health(**admin.health(db))


@router.get("/admin/flags", response_model=Flags)
def get_flags(db: Session = Depends(get_db), user: User = Depends(admin_only)) -> Flags:
    return Flags(**faults.get_flags(db))


@router.put("/admin/flags", response_model=Flags)
def put_flags(
    body: FlagsUpdate, db: Session = Depends(get_db), user: User = Depends(admin_only)
) -> Flags:
    flags = faults.set_flags(db, body.model_dump(exclude_none=True), user)
    db.commit()
    return Flags(**flags)


@router.post("/admin/reset-demo", status_code=204)
def reset_demo(db: Session = Depends(get_db), user: User = Depends(admin_only)) -> None:
    admin.reset_demo(db, user)


@router.get("/samples", response_model=list[Sample])
def samples(user: User = Depends(get_current_user)) -> list[Sample]:
    return [Sample(**s) for s in SAMPLES]


@router.get("/inventory", response_model=list[InventoryOut])
def list_inventory(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[InventoryOut]:
    return [InventoryOut.model_validate(r) for r in inventory.list_items(db)]


@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[SupplierOut]:
    return [SupplierOut.model_validate(s) for s in inventory.list_suppliers(db)]
