"""Case lifecycle: allowed transitions only; illegal moves return 409 ILLEGAL_TRANSITION."""

from __future__ import annotations

import pytest

from app.enums import Status
from app.errors import ApiError
from app.models import Case
from app.state_machine import ALLOWED, TERMINAL, allowed_targets, can_transition
from tests.conftest import Api


def _case(status: Status, previous: Status | None = None) -> Case:
    return Case(status=str(status), previous_status=str(previous) if previous else None)


def test_terminal_states_are_final() -> None:
    for status in (Status.CLOSED, Status.CANCELLED):
        assert allowed_targets(_case(status)) == frozenset()
    assert allowed_targets(_case(Status.DUPLICATE)) == {Status.ANALYZING}  # only "not duplicate"


def test_any_open_status_can_hold_or_cancel() -> None:
    for status in set(ALLOWED) - TERMINAL - {Status.ON_HOLD}:
        assert can_transition(_case(status), Status.ON_HOLD)
        assert can_transition(_case(status), Status.CANCELLED)


def test_on_hold_returns_to_previous() -> None:
    held = _case(Status.ON_HOLD, previous=Status.IN_PROGRESS)
    assert allowed_targets(held) == {Status.IN_PROGRESS, Status.ANALYZING, Status.CANCELLED}


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (Status.NEW, Status.CLOSED),
        (Status.PENDING_REVIEW, Status.APPROVED),
        (Status.IN_PROGRESS, Status.CLOSED),
        (Status.PENDING_APPROVAL, Status.IN_PROGRESS),
        (Status.CLOSED, Status.IN_PROGRESS),
    ],
)
def test_illegal_transitions_rejected(current: Status, target: Status) -> None:
    assert not can_transition(_case(current), target)


def test_transition_raises_409(db: object) -> None:
    from app.state_machine import transition

    case = _case(Status.PENDING_REVIEW)
    case.version = 1
    with pytest.raises(ApiError) as err:
        transition(db, case, Status.CLOSED, actor="test")  # type: ignore[arg-type]
    assert err.value.status_code == 409 and err.value.code == "ILLEGAL_TRANSITION"


def test_api_illegal_transition_409(api: Api) -> None:
    case = api.create_sample("happy_path")
    res = api.post(f"/requests/{case['id']}/transition", {"to": "CLOSED", "reason": "skip"})
    assert res.status_code == 409 and res.json()["code"] == "ILLEGAL_TRANSITION"
    res = api.post(f"/requests/{case['id']}/transition", {"to": "APPROVED"})
    assert res.status_code == 409


def test_hold_and_resume(api: Api) -> None:
    case = api.create_sample("happy_path")
    res = api.post(f"/requests/{case['id']}/transition", {"to": "ON_HOLD", "reason": "Waiting"})
    assert res.json()["status"] == "ON_HOLD" and "resume" in res.json()["allowed_actions"]
    res = api.post(f"/requests/{case['id']}/transition", {"to": "PENDING_REVIEW"})
    assert res.status_code == 200 and res.json()["status"] == "PENDING_REVIEW"
