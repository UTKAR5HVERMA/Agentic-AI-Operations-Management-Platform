"""Edge case 11: unauthorized actions are blocked server-side and audited (`auth.denied`)."""

from __future__ import annotations

from tests.conftest import (
    ADMIN,
    MANAGER,
    MANAGER_NORTH,
    OPS_TEAM,
    REQUESTER,
    Api,
    audit_actions,
)


def _pending_approval(api: Api, sample: str = "happy_path", **kw: object) -> tuple[dict, dict]:
    case = api.select(api.create_sample(sample, **kw))
    return case, case["approvals"][0]


def test_rbac_requester_cannot_approve(api: Api) -> None:
    _, approval = _pending_approval(api)
    res = api.post(f"/approvals/{approval['id']}/approve", {}, as_=REQUESTER)
    assert res.status_code == 403
    assert "auth.denied" in audit_actions()


def test_rbac_only_assigned_manager_decides(api: Api) -> None:
    _, approval = _pending_approval(api)  # Pune → pre-assigned to the West manager
    assert approval["assigned_to"]["name"] == "Priya Manager"
    res = api.post(f"/approvals/{approval['id']}/approve", {}, as_=MANAGER_NORTH)
    assert res.status_code == 403 and res.json()["code"] == "NOT_ASSIGNED_APPROVER"
    assert res.json()["detail"] == "This approval is assigned to Priya Manager."


def test_ops_team_routes_to_chosen_manager(api: Api) -> None:
    approvers = api.get("/approvals/approvers").json()
    north = next(m for m in approvers if m["region"] == "North")
    case = api.create_sample("happy_path")
    rec = case["recommendations"][0]
    res = api.post(
        f"/requests/{case['id']}/recommendations/{rec['id']}/select", {"approver_id": north["id"]}
    )
    assert res.status_code == 200, res.text
    approval = res.json()["approvals"][0]
    assert approval["assigned_to"]["id"] == north["id"]
    # The chosen manager can see and decide a case outside their region; the region's own
    # manager cannot decide someone else's assignment.
    assert api.get(f"/requests/{case['id']}", as_=MANAGER_NORTH).status_code == 200
    blocked = api.post(f"/approvals/{approval['id']}/approve", {}, as_=MANAGER)
    assert blocked.status_code == 403 and blocked.json()["code"] == "NOT_ASSIGNED_APPROVER"
    ok = api.post(f"/approvals/{approval['id']}/approve", {}, as_=MANAGER_NORTH)
    assert ok.status_code == 200, ok.text
    assert api.case(case["id"])["status"] == "IN_PROGRESS"


def test_invalid_approver_rejected(api: Api) -> None:
    case = api.create_sample("happy_path")
    rec = case["recommendations"][0]
    analyst_id = api.get("/auth/me").json()["id"]
    res = api.post(
        f"/requests/{case['id']}/recommendations/{rec['id']}/select", {"approver_id": analyst_id}
    )
    assert res.status_code == 400 and res.json()["code"] == "INVALID_APPROVER"


def test_rbac_limit_exceeded(api: Api) -> None:
    case = api.create_sample("happy_path")
    expedite = next(r for r in case["recommendations"] if r["kind"] == "expedite")
    case = api.select(case, rank=expedite["rank"])  # ₹1,47,000 > the manager's ₹50,000 limit
    approval = case["approvals"][0]
    assert len(case["approvals"]) == 1  # one decision: the manager's
    assert approval["approver_role"] == "ops_manager" and approval["kind"] == "financial"

    res = api.post(f"/approvals/{approval['id']}/approve", {}, as_=MANAGER)
    assert res.status_code == 403 and res.json()["code"] == "APPROVAL_LIMIT_EXCEEDED"
    assert res.json()["detail"] == "You can approve up to ₹50,000. Forward it to the Director."

    res = api.post(f"/approvals/{approval['id']}/escalate", {"note": "Needs Director"}, as_=MANAGER)
    assert res.status_code == 200 and res.json()["approver_role"] == "admin"
    assert "approval.forwarded" in audit_actions(case["id"])
    res = api.post(f"/approvals/{approval['id']}/approve", {"note": "Approved"}, as_=ADMIN)
    assert res.status_code == 200, res.text
    assert api.case(case["id"])["status"] == "IN_PROGRESS"


def test_manager_may_forward_small_amounts(api: Api) -> None:
    case, approval = _pending_approval(api)  # ₹42,000: within the manager's limit
    res = api.post(
        f"/approvals/{approval['id']}/escalate", {"note": "Director's call"}, as_=MANAGER
    )
    assert res.status_code == 200 and res.json()["approver_role"] == "admin"
    assert api.case(case["id"])["priority"] == case["priority"]  # a forward is not an SLA breach


def test_rbac_self_approval_blocked(api: Api) -> None:
    _, approval = _pending_approval(api, sender_email=MANAGER)
    res = api.post(f"/approvals/{approval['id']}/approve", {}, as_=MANAGER)
    assert res.status_code == 403 and res.json()["code"] == "SELF_APPROVAL"


def test_rbac_logging_a_request_is_not_raising_it(api: Api) -> None:
    # The Director logs a request on behalf of a sender (Scenario Lab / New request): above the
    # manager limit the Director must still be able to approve it.
    case = api.create_sample("happy_path", submit_as=ADMIN)
    expedite = next(r for r in case["recommendations"] if r["kind"] == "expedite")
    case = api.select(case, rank=expedite["rank"])
    approval = case["approvals"][0]
    assert (
        api.post(
            f"/approvals/{approval['id']}/escalate", {"note": "Over my limit"}, as_=MANAGER
        ).status_code
        == 200
    )
    res = api.post(f"/approvals/{approval['id']}/approve", {}, as_=ADMIN)
    assert res.status_code == 200, res.text


def test_rbac_director_self_approval_needs_justification(api: Api) -> None:
    # The Director is the sender and nobody is above them: a plain approve is refused, an
    # override with a written justification is allowed, flagged and reported for review.
    case, own = _pending_approval(api, submit_as=ADMIN, sender_email=ADMIN)
    view = api.get(f"/requests/{case['id']}", as_=ADMIN).json()
    assert view["approvals"][0]["needs_self_override"]
    res = api.post(f"/approvals/{own['id']}/approve", {}, as_=ADMIN)
    assert res.status_code == 403 and res.json()["code"] == "SELF_APPROVAL_OVERRIDE_REQUIRED"

    short = {"self_override": True, "note": "ok"}
    res = api.post(f"/approvals/{own['id']}/approve", short, as_=ADMIN)
    assert res.status_code == 400 and res.json()["code"] == "JUSTIFICATION_REQUIRED"

    why = "Launch is tomorrow; no other approver is available today."
    res = api.post(
        f"/approvals/{own['id']}/approve", {"self_override": True, "note": why}, as_=ADMIN
    )
    assert res.status_code == 200, res.text
    assert res.json()["self_approved"] and res.json()["status"] == "approved"
    assert "approval.self_override" in audit_actions(case["id"])
    dashboard = api.get("/reports/dashboard", as_=ADMIN).json()
    assert dashboard["self_approvals"][0]["justification"] == why


def test_rbac_manager_cannot_override_own_request(api: Api) -> None:
    _, own = _pending_approval(api, sender_email=MANAGER)
    res = api.post(
        f"/approvals/{own['id']}/approve",
        {"self_override": True, "note": "I really want this approved"},
        as_=MANAGER,
    )
    assert res.status_code == 403 and res.json()["code"] == "SELF_APPROVAL"  # managers: never


def test_rbac_requester_cannot_view_others(api: Api) -> None:
    case = api.create_sample("happy_path", submit_as=OPS_TEAM)
    res = api.get(f"/requests/{case['id']}", as_=REQUESTER)
    assert res.status_code == 403 and res.json()["code"] == "CASE_ACCESS_DENIED"
    assert api.get("/requests", as_=REQUESTER).json() == []


def test_rbac_requester_sees_own_and_cannot_select(api: Api) -> None:
    case = api.create_sample("happy_path", as_=REQUESTER, sender_email=REQUESTER)
    own = api.case(case["id"], as_=REQUESTER)
    assert "select_recommendation" not in own["allowed_actions"]
    rec = own["recommendations"][0]
    res = api.post(f"/requests/{case['id']}/recommendations/{rec['id']}/select", {}, as_=REQUESTER)
    assert res.status_code == 403


def test_rbac_north_manager_cannot_view_west_case(api: Api) -> None:
    case = api.create_sample("happy_path")
    assert api.get(f"/requests/{case['id']}", as_=MANAGER_NORTH).status_code == 403


def test_rbac_ops_team_routes_but_cannot_approve(api: Api) -> None:
    north = api.create_sample("low_confidence")  # Delhi → North; the triage desk sees all regions
    assert north["region"] == "North"
    _, approval = _pending_approval(api)
    res = api.post(f"/approvals/{approval['id']}/approve", {}, as_=OPS_TEAM)
    assert res.status_code == 403 and res.json()["code"] == "NOT_AN_APPROVER"
    assert "auth.denied" in audit_actions()


def test_rbac_manager_only_sees_cases_routed_by_ops_team(api: Api) -> None:
    case = api.create_sample("happy_path")  # Pune → West, still with the Operations Team
    res = api.get(f"/requests/{case['id']}", as_=MANAGER)
    assert res.status_code == 403 and "not been routed to you yet" in res.json()["detail"]
    assert api.get("/requests", as_=MANAGER).json() == []
    rec = case["recommendations"][0]
    res = api.post(f"/requests/{case['id']}/recommendations/{rec['id']}/select", {}, as_=MANAGER)
    assert res.status_code == 403  # whoever approves never proposes (segregation of duties)

    note = "Please approve the Mumbai transfer; launch is next week."
    res = api.post(f"/requests/{case['id']}/recommendations/{rec['id']}/select", {"note": note})
    assert res.status_code == 200, res.text
    routed = api.case(case["id"], as_=MANAGER)  # now visible to the West manager
    assert routed["approvals"][0]["routing_note"] == note
    assert "select_recommendation" not in routed["allowed_actions"]
    assert {"approve", "hold", "cancel"} <= set(routed["allowed_actions"])
    email = next(c for c in routed["communications"] if c["type"] == "approval_request")
    assert note in email["body"]  # the Ops Team's note travels with the request …
    assert "Original request" in email["body"] and "500 display units" in email["body"]
    assert api.get("/requests", as_=MANAGER_NORTH).json() == []  # … to the right region only


def test_rbac_admin_endpoints_require_admin(api: Api) -> None:
    assert api.put("/admin/flags", {"llm_down": True}, as_=MANAGER).status_code == 403
    assert api.post("/simulate/scheduler-tick", as_=MANAGER).status_code == 403
    assert api.post("/admin/reset-demo", as_=MANAGER).status_code == 403
    assert api.get("/audit", as_=REQUESTER).status_code == 403


def test_rbac_unauthenticated_and_webhook(api: Api) -> None:
    assert api.client.get("/api/requests").status_code == 401
    body = {"subject": "x", "raw_text": "y"}
    bad = api.client.post(
        "/api/requests/ingest-email", json=body, headers={"X-Webhook-Secret": "wrong"}
    )
    assert bad.status_code == 401 and bad.json()["code"] == "INVALID_WEBHOOK_SECRET"
    ok = api.client.post(
        "/api/requests/ingest-email", json=body, headers={"X-Webhook-Secret": "test-webhook-secret"}
    )
    assert ok.status_code == 201 and ok.json()["channel"] == "email"


def test_login_flow(api: Api) -> None:
    bad = api.client.post("/api/auth/login", json={"email": MANAGER, "password": "nope"})
    assert bad.status_code == 401 and bad.json()["code"] == "INVALID_CREDENTIALS"
    ok = api.client.post("/api/auth/login", json={"email": MANAGER, "password": "Demo@123"})
    assert ok.status_code == 200
    token = ok.json()["access_token"]
    me = api.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["role"] == "ops_manager" and me["approval_limit_inr"] == 50_000
    assert {"auth.login_failed", "auth.login"} <= set(audit_actions())
