# OpsPilot — Agentic AI Operations Management Platform

[![CI](https://github.com/<your-github-user>/<repo>/actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)

OpsPilot turns unstructured operations emails (delivery delays, stock shortages, urgent orders)
into tracked cases. A team of LLM agents reads each request, extracts its facts with
evidence, checks them against inventory, finds missing or conflicting information, assesses risk
and recommends actions. **LLMs propose and policy decides.** Every binding step (approval,
sending, cancelling, changing status) is made by deterministic code or a human, and every action
is written to a hash-chained audit trail.

| | |
|---|---|
| **Live app** | `<add live URL>` |
| **Demo password** | `Demo@123` (all accounts) |
| **Stack** | FastAPI · SQLAlchemy · LangGraph · Postgres · React 18 + TypeScript · Vite · Tailwind · TanStack Query |
| **LLM** | Groq `openai/gpt-oss-120b` via the OpenAI-compatible API (any OpenAI-compatible provider works) |

---

## Contents
1. [Demo accounts](#1-demo-accounts)
2. [Architecture](#2-architecture)
3. [Quick start (Docker, 3 commands)](#3-quick-start-docker-3-commands)
4. [Manual setup (backend + frontend)](#4-manual-setup-backend--frontend)
5. [Environment variables](#5-environment-variables)
6. [Running tests & linters](#6-running-tests--linters)
7. [Edge cases handled](#7-edge-cases-handled)
8. [How the AI is kept safe](#8-how-the-ai-is-kept-safe)
9. [API overview](#9-api-overview)
10. [Deployment](#10-deployment)
11. [Troubleshooting](#11-troubleshooting)
12. [Assumptions, trade-offs & roadmap](#12-assumptions-trade-offs--roadmap)

---

## 1. Demo accounts

All accounts use the password **`Demo@123`**. They are created automatically on first start.

| Role | Email | What they can do |
|---|---|---|
| Requester (request desk) | `requester@opspilot.demo` | Submit requests as any sample sender and track business status only |
| Operations Team | `ops.team@opspilot.demo` | Central triage desk for all regions. Reviews AI output, corrects fields, selects or overrides recommendations, routes for approval |
| Regional Manager (West) | `manager@opspilot.demo` | Approve up to ₹50,000, reject, or forward to the Director. Hold, resume or cancel cases |
| Regional Manager (North) | `manager.north@opspilot.demo` | Same as above, for North-region cases |
| Director (admin) | `admin@opspilot.demo` | Approves above ₹50,000. Opens the Scenario Lab, sets fault flags, resets the demo |

---

## 2. Architecture

```
                ┌───────────────────────── React SPA (Vite, TS) ─────────────────────────┐
                │ Login · Requests · New Request · Case Detail · Approvals · Dashboard   │
                │ Reports · Audit · Scenario Lab        (buttons from `allowed_actions`) │
                └───────────────────────────────┬────────────────────────────────────────┘
                                                │ /api (JWT)
┌───────────────────────────────────────────────▼────────────────────────────────────────┐
│ FastAPI                                                                                │
│  routers/  → HTTP only (parse, auth, call service)                                     │
│  services/ → business logic, transactions, state machine, audit                        │
│  agents/   → LangGraph pipeline (pure functions of CaseState)                          │
│  llm/      → the ONLY place that calls the LLM (timeout, retries, schema, fallback)    │
│  scheduler → approval timeouts / escalations, retries, picks up unanalysed cases       │
└───────────────┬───────────────────────────────────────────────┬────────────────────────┘
                │                                               │
        Postgres (SQLite in tests)                  OpenAI-compatible LLM (Groq)
        cases · approvals · comms · audit_log (hash chain)
```

**Agent pipeline** (`backend/app/agents/graph.py`)

```
IntakeGuard (prompt-injection) → Dedup → Extraction → Validation (vs inventory)
   → OpsRisk ┐
   → FinancialRisk ┴→ Risk reconciler → Recommendation → Confidence → ApprovalRouter (deterministic)
                                                            → Communication drafts → Reporting
```

The agents share context through a single `CaseState` object. Each agent returns a partial
update, and the service layer persists it. Agents never write to the database.

---

## 3. Quick start (Docker, 3 commands)

Requires **Docker Desktop** (or Docker Engine + Compose v2).

```bash
cp .env.example backend/.env            # 1. config (add LLM_API_KEY, or set LLM_MODE=mock)
docker compose --profile app up -d --build   # 2. builds the app image + starts Postgres
open http://localhost:8000              # 3. log in with a demo account
```

> On Windows PowerShell use `Copy-Item .env.example backend\.env` and open the URL in a browser.

The app container builds the React frontend, serves it from FastAPI on port **8000**, creates
the tables and seeds the demo data on first start.

Useful commands:

```bash
docker compose logs -f app                    # follow logs
docker compose --profile app down             # stop
docker compose --profile app down -v          # stop and wipe the database
```

---

## 4. Manual setup (backend + frontend)

### Prerequisites
| Tool | Version |
|---|---|
| Python | 3.11+ (3.12 recommended) |
| Node.js | 24 (with npm) |
| Docker | Only for the local Postgres. You can use SQLite instead, see below |

### 4.1 Clone and configure

```bash
git clone https://github.com/<your-github-user>/<repo>.git
cd <repo>
cp .env.example backend/.env
```

Edit `backend/.env`:
- **With an LLM:** put your Groq key in `LLM_API_KEY` (free key at <https://console.groq.com/keys>).
- **Without an LLM:** set `LLM_MODE=mock`. Deterministic fallbacks run instead, which is fully offline.
- Change `JWT_SECRET` and `WEBHOOK_SECRET` to long random strings.

### 4.2 Database

**Option A: Postgres in Docker (recommended).** It uses host port **5433**, so it does not clash
with a local Postgres on 5432:

```bash
docker compose up -d db
```

The default `DATABASE_URL` in `.env.example` already points at it.

**Option B: SQLite (zero setup).** In `backend/.env` set:

```
DATABASE_URL=sqlite:///./opspilot.db
```

### 4.3 Backend

Create the virtualenv at the repo root, then run everything from `backend/`:

```bash
# from the repo root
python -m venv venv
# Windows:      venv\Scripts\activate
# macOS/Linux:  source venv/bin/activate
pip install -r backend/requirements.txt

cd backend
python -m uvicorn app.main:app --reload
```

- API: <http://localhost:8000/api>
- Interactive API docs (Swagger): <http://localhost:8000/docs>
- Health check: <http://localhost:8000/api/health>

On startup the backend creates the tables, seeds the demo users, inventory, suppliers and sample
requests (`SEED_ON_STARTUP=true`), and starts the background scheduler.

### 4.4 Frontend

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` to `http://localhost:8000`, so no extra CORS
setup is needed.

### 4.5 Try the end-to-end flow
1. Log in as **requester@opspilot.demo** → *New Request*, then pick sample 1, *"Urgent Delivery Delay – Store Launch"*, and submit.
2. Log in as **ops.team@opspilot.demo** → open the case. Review the extraction (with evidence), the conflict between the email's 120 units and inventory's 80, the risk and the recommendations. Select an option and route it to the Regional Manager.
3. Log in as **manager@opspilot.demo** → *Approvals* → approve.
4. Back as the Operations Team: edit and send the stakeholder emails, then resolve and close the case.
5. Use *Reports* to generate the management summary and *Audit* to verify the hash chain.

---

## 5. Environment variables

All settings are read in `backend/app/config.py` from `backend/.env`. A template lives in
[`.env.example`](.env.example). **Never commit `backend/.env`.**

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./opspilot.db` | SQLAlchemy URL. Postgres: `postgresql+psycopg://opspilot:opspilot@localhost:5433/opspilot` |
| `JWT_SECRET` | `change-me` | Secret used to sign login tokens. **Change this** |
| `JWT_EXPIRE_MINUTES` | `720` | Token lifetime |
| `LLM_MODE` | `live` | `live` calls the LLM. `mock` uses the deterministic fallbacks (tests, offline) |
| `LLM_BASE_URL` | Gemini OpenAI endpoint | Any OpenAI-compatible base URL, e.g. `https://api.groq.com/openai/v1/` |
| `LLM_API_KEY` | *(empty)* | Provider API key. If it is empty, the app runs in degraded mode with fallbacks |
| `LLM_MODEL` | `gemini-3.5-flash` | e.g. `openai/gpt-oss-120b` on Groq |
| `LLM_TIMEOUT_SECONDS` | `20` | Per-call timeout |
| `LLM_MAX_RETRIES` | `2` | Retries before falling back |
| `LLM_REASONING_EFFORT` | *(empty)* | `low` / `medium` / `high` for reasoning models (gpt-oss). Leave empty for Gemini |
| `LLM_MAX_CALLS_PER_RUN` | `8` | Budget guard: max LLM calls per case analysis |
| `CONFIDENCE_AUTO_THRESHOLD` | `0.80` | At or above this, the recommendation is shown as high confidence |
| `CONFIDENCE_BLOCK_THRESHOLD` | `0.50` | Below this, the recommendation is withheld and a human must decide |
| `APPROVAL_DEFAULT_TIMEOUT_MINUTES` | `60` | Approval SLA before automatic escalation |
| `SCHEDULER_INTERVAL_SECONDS` | `30` | Background scheduler tick |
| `SCHEDULER_ENABLED` | `true` | Turn the scheduler on or off |
| `SEED_ON_STARTUP` | `true` | Seed demo data when the database is empty |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated list of allowed origins |
| `WEBHOOK_SECRET` | `change-me-webhook-secret` | Required `X-Webhook-Secret` header for `/api/requests/ingest-email` |
| `LOG_LEVEL` | `INFO` | Log level (structured JSON logs) |

**Switching LLM provider** only needs env changes. For example, for Gemini:

```
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_MODEL=gemini-3.5-flash
LLM_REASONING_EFFORT=
```

---

## 6. Running tests & linters

Tests run with `LLM_MODE=mock` and a fresh SQLite database per test. They do not need internet,
Postgres or an API key.

```bash
# Backend (from backend/, with the venv active)
python -m pytest -q          # 104 tests, all passing
ruff check .
ruff format --check .

# Frontend (from frontend/)
npm run lint                 # ESLint + Prettier check
npm test                     # Vitest component and flow tests
npm run build                # type-check + production build
```

CI (`.github/workflows/ci.yml`) runs all of the above on every push and pull request to `main`.

---

## 7. Edge cases handled

Each edge case has a test that checks four things: **detect** the issue, **communicate** it,
**recover** from it, and **record** it in the audit trail. Most can be triggered from the
**Scenario Lab** (Director login) or with the sample emails on *New Request*.

| # | Edge case | How it is handled | Test |
|---|---|---|---|
| 1 | Missing information | Issue chips + an info request drafted to the sender | `test_missing_info` |
| 2 | Conflicting information | Email says 120 units, inventory says 80: conflict card, inventory used | `test_inventory_conflict` |
| 3 | Duplicate requests | Similar recent case linked; staff confirm or reject the duplicate | `test_duplicate_detection` |
| 4 | Multi-issue / unclear intent | All issues tracked inside one case, never split | `test_multi_issue_handled_in_case` |
| 5 | Incorrect AI extraction | Human corrects a field, which re-runs the downstream agents | `test_field_correction_reruns_downstream` |
| 6 | Low-confidence recommendation | Recommendation withheld, human decision required | `test_low_confidence_withholds_recommendation` |
| 7 | Approval delay | Scheduler escalates when the SLA expires | `test_approval_timeout_escalates` |
| 8 | Approval rejection | An alternative option is re-proposed | `test_rejection_reproposes_alternative` |
| 9 | Changing circumstances | Supplier revision triggers reassessment | `test_supplier_revision_reassesses` |
| 10 | LLM / system unavailable | Deterministic fallback with a degraded-mode banner | `test_llm_down_uses_fallback`, `test_inventory_down_uses_email_value` |
| 11 | Unauthorized action | Server-side RBAC, region checks, approval limit, no self-approval | `test_rbac_*` |
| 12 | Prompt injection | Regex + LLM classifier, malicious spans quarantined | `test_prompt_injection_quarantined` |
| 13 | Communication failure | Send retried with backoff | `test_comm_failure_retries` |
| 14 | Contradictory agent outputs | Reconciler flags the disagreement between the risk agents | `test_agent_disagreement` |
| 15 | Request cancellation | Pending approvals cancelled automatically | `test_cancel_cancels_pending_approvals` |
| — | Concurrent edits | Optimistic locking returns `409 STALE_VERSION` | `test_stale_version_rejected` |

---

## 8. How the AI is kept safe

- **Human approval is mandatory** for every approval, outbound email, cancellation and status
  change. No LLM output can trigger these, and the code has no path that allows it.
- **Confidence** is computed by code (`agents/confidence.py`), not taken from the LLM's own
  claim: `overall = 0.4·extraction + 0.2·data + 0.2·risk_agreement + 0.2·recommendation`.
  A recommendation can't score more than 0.3 above its extraction confidence, and fallback output
  is capped at 0.6. A score of `≥ 0.80` is *recommended*, `0.50–0.80` is *needs review*, and
  below `0.50` the recommendation is *withheld*.
- **Unsupported or incorrect output** goes through several checks: JSON schema validation with one
  repair retry, grounding (each extracted value must quote evidence from the email), reference
  checks against inventory and suppliers, and numeric bounds. After that, the deterministic
  fallback takes over. Unsupported recommendations are discarded and logged.
- **Prompt injection** is checked by regex and an LLM classifier. Untrusted email text is always
  wrapped in `<untrusted_email>` tags, and suspicious spans are quarantined.
- **Audit**: every AI and human action is written to `audit_log` with the actor, model, prompt
  hash, latency and outcome. Rows are hash-chained, and `GET /api/audit/verify` proves that
  nothing was altered.

---

## 9. API overview

Full interactive docs are at `/docs` while the backend runs. Main groups:

| Prefix | Purpose |
|---|---|
| `POST /api/auth/login`, `GET /api/auth/me` | Authentication (JWT) |
| `/api/requests` | Create, list and view cases. Correct fields, select or override recommendations, transition, cancel, add events, generate communications |
| `POST /api/requests/ingest-email` | Email webhook (header `X-Webhook-Secret`) |
| `/api/approvals` | List, approve, reject, escalate |
| `/api/communications` | Edit, delete and send drafts |
| `/api/reports` | Dashboard metrics, management summary |
| `/api/audit`, `/api/audit/verify` | Audit trail and hash-chain verification |
| `/api/admin/*`, `/api/simulate/*` | Fault flags, demo reset, simulated timeouts (Director only) |
| `GET /api/health` | Component health (used by the container health check) |

Example webhook call:

```bash
curl -X POST http://localhost:8000/api/requests/ingest-email \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: <WEBHOOK_SECRET>" \
  -d '{"subject":"Delivery delay","raw_text":"We need 200 racks in Pune by Friday...","sender_email":"store@example.com"}'
```

---

## 10. Deployment

The production build is a **single Docker image**: the React build is served as static files by
FastAPI. It runs on an Oracle Cloud free VM together with Postgres.

```bash
# on the VM
git clone https://github.com/<your-github-user>/<repo>.git && cd <repo>
cp .env.example backend/.env     # set LLM_API_KEY, JWT_SECRET, WEBHOOK_SECRET, CORS_ORIGINS
docker compose --profile app up -d --build
```

- Open port **8000** in the VM's security list and firewall, or put a reverse proxy (Caddy or Nginx) in front for HTTPS on 443.
- Set `CORS_ORIGINS` to the public URL.
- After deploying, run a quick check: log in → submit sample 1 → open the case → approve → `GET /api/audit/verify`.
- `POST /api/admin/reset-demo` (Director) restores the demo data.

Backend-only image (no frontend): `docker build --target api -t opspilot-api .`

---

## 11. Troubleshooting

| Problem | Fix |
|---|---|
| `connection refused` on port 5433 | Start the database: `docker compose up -d db` (check it with `docker compose ps`) |
| Port 5432 / 5433 already in use | Change the host port in `docker-compose.yml` and in `DATABASE_URL` |
| Banner says "LLM unavailable / degraded mode" | `LLM_API_KEY` is missing or invalid, or the provider is rate-limiting. The app keeps working with fallbacks |
| Frontend shows network errors | Make sure the backend is running on `:8000` before `npm run dev` |
| CORS error in production | Add the site's origin to `CORS_ORIGINS` |
| Want a clean database | Docker: `docker compose --profile app down -v`. SQLite: delete `backend/opspilot.db` |
| `passlib` / `bcrypt` errors | Not used. Passwords are hashed with `hashlib.pbkdf2_hmac` |

---

## 12. Assumptions, trade-offs & roadmap

**Assumptions**
- Approval limit: a Regional Manager approves up to ₹50,000. The Director approves above that.
- One central Operations Team triages all regions and chooses which Regional Manager decides.
- Inventory and supplier systems are simulated with seeded tables.
- Outbound email delivery is simulated, with delivery status and retries.

**Trade-offs**
- The scheduler runs inside the app process instead of a separate worker queue. This is simpler to run, but limits the app to a single instance.
- Tests use SQLite for speed. Production uses Postgres.
- Multi-issue emails are tracked in one case instead of being split into child cases.

**Roadmap**
- Real mailbox integration (IMAP / Microsoft Graph) and real ERP / inventory connectors
- SSO (OIDC) and per-tenant configuration
- A separate worker queue (Redis or Celery) for horizontal scaling
- Evaluation harness and prompt regression tracking across models
