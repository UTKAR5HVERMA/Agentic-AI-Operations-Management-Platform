"""Clarification drafts: one combined draft per case, reused instead of duplicated, deletable."""

from __future__ import annotations

from tests.conftest import REQUESTER, Api, audit_actions


def _clarifications(case: dict) -> list[dict]:
    return [c for c in case["communications"] if c["type"] == "clarification"]


def test_one_clarification_covers_every_open_question_and_is_reused(api: Api) -> None:
    case = api.create_sample("happy_path")  # open: conflict 120 vs 80, missing supplier, …
    first = api.post(
        f"/requests/{case['id']}/communications/generate", {"type": "clarification"}
    ).json()
    body = first["body"].lower()
    assert "supplier" in body and "our inventory shows" in body  # missing + conflict, with context

    again = api.post(
        f"/requests/{case['id']}/communications/generate", {"type": "clarification"}
    ).json()
    assert again["id"] == first["id"]  # asking again opens the same draft
    assert len(_clarifications(api.case(case["id"]))) == 1


def test_draft_can_be_deleted_but_not_once_sent(api: Api) -> None:
    case = api.create_sample("happy_path")
    draft = api.post(
        f"/requests/{case['id']}/communications/generate", {"type": "clarification"}
    ).json()
    res = api.client.delete(f"/api/communications/{draft['id']}", headers=api.headers(OPS))
    assert res.status_code == 204
    assert not _clarifications(api.case(case["id"]))  # hidden from the case
    assert "comm.discarded" in audit_actions(case["id"])  # still recorded

    fresh = api.post(
        f"/requests/{case['id']}/communications/generate", {"type": "clarification"}
    ).json()
    assert fresh["id"] != draft["id"]  # a new draft can be made after deleting
    api.post(f"/communications/{fresh['id']}/send")
    res = api.client.delete(f"/api/communications/{fresh['id']}", headers=api.headers(OPS))
    assert res.status_code == 409 and res.json()["code"] == "COMM_NOT_DISCARDABLE"


OPS = "ops.team@opspilot.demo"


def _send_clarification(api: Api, case: dict) -> dict:
    draft = api.post(
        f"/requests/{case['id']}/communications/generate", {"type": "clarification"}
    ).json()
    api.post(f"/communications/{draft['id']}/send")
    return draft


def test_requester_replies_with_ai_draft_while_under_review(api: Api) -> None:
    case = api.create_sample("happy_path")  # PENDING_REVIEW, not NEEDS_INFO
    _send_clarification(api, case)
    mine = api.case(case["id"], as_=REQUESTER)
    assert "provide_info" in mine["allowed_actions"]  # can answer while under review

    notes = "supplier is DisplayCo, original delivery was 6 Nov"
    res = api.post(f"/requests/{case['id']}/compose-reply", {"text": notes}, as_=REQUESTER)
    assert res.status_code == 200, res.text
    reply = res.json()["body"]
    assert "DisplayCo" in reply  # drafted from their notes; nothing saved yet
    assert not [c for c in api.case(case["id"])["communications"] if c["type"] == "requester_reply"]

    res = api.post(
        f"/requests/{case['id']}/provide-info",
        {"text": reply, "version": mine["version"]},
        as_=REQUESTER,
    )
    assert res.status_code == 200, res.text
    staff = api.case(case["id"])
    answer = next(c for c in staff["communications"] if c["type"] == "requester_reply")
    assert answer["status"] == "sent" and answer["subject"].startswith("Re: ")
    assert "comm.reply_received" in audit_actions(case["id"])
    assert "DisplayCo" in staff["raw_text"]  # appended, so the agents re-ran with it


def test_llm_placeholders_are_removed() -> None:
    from app.agents.communication import _PLACEHOLDER

    body = "Thanks,\n[Your Name]\nOperations Team"
    assert _PLACEHOLDER.sub("", body) == "Thanks,\nOperations Team"


MUMBAI = (
    "Hi Operations Team,\n\nShelfMart has informed us that the delivery of 300 shelving racks for "
    "the Mumbai store will be delayed by five days. This delay affects the store refit schedule, "
    "which requires the racks by 10 Nov.\n\nPlease coordinate with ShelfMart to expedite the "
    "shipment or arrange an alternative solution.\n\nThank you,\nMumbai Ops"
)


def test_answer_closes_the_questions_and_updates_the_draft(api: Api) -> None:
    res = api.post(
        "/requests",
        {
            "channel": "email",
            "subject": "Delivery delay for 300 shelving racks",
            "raw_text": MUMBAI,
            "sender_email": "mumbai.ops@opspilot.demo",
            "sender_name": "Mumbai Ops",
            "received_at": "2026-11-03T10:00:00+05:30",
        },
        as_=REQUESTER,
    )
    case = api.case(res.json()["id"])
    asked = _send_clarification(api, case)
    assert "original delivery date" in asked["body"].lower()  # asked, with the reason why
    assert "our inventory shows 150 free at mumbai-wh" in asked["body"].lower()
    pending = api.post(
        f"/requests/{case['id']}/communications/generate", {"type": "clarification"}
    ).json()  # a second, still unsent draft

    answer = "Quantity currently available: 120 racks\nOriginal delivery date: 5 Nov 2026"
    mine = api.case(case["id"], as_=REQUESTER)
    res = api.post(
        f"/requests/{case['id']}/provide-info",
        {"text": answer, "version": mine["version"]},
        as_=REQUESTER,
    )
    assert res.status_code == 200, res.text
    case = api.case(case["id"])
    open_fields = {i["field"] for i in case["issues"] if i["status"] == "open"}
    assert "original_delivery_date" not in open_fields  # 5 Nov + 5 days ≤ 10 Nov: answered
    assert next(f for f in case["fields"] if f["field"] == "original_delivery_date")
    stale = next(c for c in api.case(case["id"])["communications"] if c["id"] == pending["id"])
    assert "original delivery date" not in stale["body"].lower()  # draft follows the answers
