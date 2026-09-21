# Automated PO Tracker

Connects to a company Gmail mailbox, reads vendor emails, downloads attachments,
classifies each one (PO / GRN / Invoice / Debit Note / Credit Note / Order
Confirmation / other), extracts structured data with AI, and maintains a
centralized, automatically-computed PO tracker with a duplicate-detection and
exception-review workflow.

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the full system design (schema,
Gmail integration, AI extraction approach, matching algorithm, security model,
phasing, cost estimate). This README covers running the Phase 1 MVP.

## What's implemented (Phase 1 MVP, plus the Phase 2/3 matching engine)

- Gmail OAuth connection + polling worker that downloads every supported
  attachment (PDF/XLS/XLSX/CSV/DOC/DOCX/JPG/PNG/TIFF) from matching emails.
- AI classification + structured extraction (Claude), schema-validated before
  anything touches the database.
- Business-rule validation (arithmetic checks, GSTIN format, missing fields,
  negative/zero quantities, abnormal tax rates) - never silently "corrects" a
  number, only flags it.
- Duplicate PO detection (exact number+vendor, file hash, vendor+date+value,
  similar PO number, same email thread).
- PO/GRN/Invoice/Debit-Credit-Note matching engine (5 priority levels, incl.
  AI-assisted fuzzy matching for the last resort).
- PO status computed automatically from underlying transactions, including
  partial-delivery line tracking and overdue detection.
- Exception queue with approve/reject/correct + full audit log.
- REST API (FastAPI), a minimal dashboard (`frontend/index.html`), and Excel
  export - Excel is a reporting format only, never the database.

## Prerequisites

- Python 3.11+
- PostgreSQL 14+ (or use `docker-compose up db` for a local instance)
- A Google Cloud project with the Gmail API enabled and an OAuth 2.0 "Web
  application" client (Console -> APIs & Services -> Credentials)
- An Anthropic API key

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in DATABASE_URL, GOOGLE_CLIENT_ID/SECRET, ANTHROPIC_API_KEY
```

Start Postgres (or point `DATABASE_URL` at an existing instance):

```bash
docker-compose up -d db
```

Run migrations:

```bash
alembic upgrade head
```

Start the API:

```bash
uvicorn backend.app.main:app --reload
```

Open the dashboard at `http://localhost:8000/dashboard/` (API at
`http://localhost:8000/api`, interactive docs at `http://localhost:8000/docs`).

Create the first admin user (needed before you can log in or connect Gmail):

```bash
python - <<'PY'
from backend.app.db import SessionLocal, Base, engine
from backend.app.models import User, UserRole
from backend.app.security import hash_password

Base.metadata.create_all(bind=engine)
db = SessionLocal()
db.add(User(email="admin@example.com", name="Admin", hashed_password=hash_password("changeme"), role=UserRole.ADMIN))
db.commit()
PY
```

Log in via `POST /api/auth/login` (form-encoded `username`/`password`) to get a
JWT, then open the dashboard and use that token (the login form in the
dashboard does this for you).

## Connecting Gmail

From the dashboard (as an admin), click **+ Connect Gmail** in the bar under
the header. That takes you to Google's consent screen; after you approve
read-only access, Google redirects back and the mailbox appears as a chip
with a **Run Ingestion Now** button (useful for testing without waiting for
the poll interval). Multiple mailboxes can be connected the same way.

Under the hood: `GET /api/auth/gmail/authorize` (admin-only) returns a Google
consent URL; Google redirects to `/api/auth/gmail/callback` with a `code`,
which is exchanged for tokens - the mailbox address itself is discovered from
Gmail's own profile API at that point (Google's redirect never tells us which
account was granted, so we ask). `GET /api/auth/gmail/mailboxes` lists
connected mailboxes, and `POST /api/ingest/run?mailbox_email=...` runs one
ingestion cycle on demand.

In production, run the background worker so ingestion happens automatically
throughout the day rather than only when you click the button:
`python -m backend.app.worker.tasks` (or `docker-compose up worker`).

`GMAIL_QUERY` in `.env` controls which mail is scanned (default:
`label:po-tracker newer_than:7d` - create a Gmail label/filter to route vendor
mail into it).

## Running tests

```bash
pytest
```

47 tests cover the section-27 test matrix: PDF/Excel/scanned/image parsing,
multi-page PDFs, unreadable attachments, PO validation (missing PO number,
arithmetic mismatches, negative quantities, abnormal tax rates, invalid
GSTIN), duplicate PO detection (all 5 checks), the matching engine (all 5
levels, multiple-match ambiguity), status computation (partial/full receipt,
overdue, closed), and end-to-end pipeline runs with the AI/Gmail calls mocked
(no API keys needed to run the suite).

## Project layout

```
ARCHITECTURE.md          Pre-build design doc (schema, integration, matching, security, phasing, cost)
backend/app/
  models.py              SQLAlchemy models (EMAILS, DOCUMENTS, PO_MASTER, PO_LINES, GRN, ...)
  schemas.py              Pydantic schemas - the AI-output <-> DB boundary
  gmail/                  OAuth, Gmail API client, email/attachment ingestion
  extraction/             File parsers (PDF/Excel/DOCX/image) + AI classification/extraction
  validation/             Business-rule validation (never auto-corrects a value)
  matching/               Duplicate PO detection + 5-level GRN/Invoice/Note matching engine
  status/                 PO status computed from underlying transactions
  pipeline.py             Orchestrates the full per-document flow
  api/routers/            FastAPI endpoints (pos, documents, emails, exceptions, dashboard, export, search, auth)
  export/                 Excel export (reporting only)
  worker/tasks.py         Scheduled Gmail polling + daily summary
frontend/index.html       Minimal PO tracker dashboard (tracker, exceptions, vendor analysis)
backend/tests/            pytest suite (AI/Gmail calls mocked)
alembic/                  DB migrations
```
