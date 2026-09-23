# Automated PO Tracker

Connects to a Gmail mailbox, reads vendor emails, downloads attachments,
classifies each one (PO / GRN / Invoice / Debit Note / Credit Note / Order
Confirmation / other), extracts structured data with AI, and maintains a
centralized, automatically-computed PO tracker with a duplicate-detection and
exception-review workflow.

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the full system design (schema,
Gmail integration, AI extraction approach, matching algorithm, security model,
phasing, cost estimate).

## Two ways to run it

1. **Local Mode** (recommended for most people) - runs entirely on your own
   computer. No hosting account, no server, no Postgres, no `.env` file to
   edit. A single file holds all your data. This is the fastest way to get
   started and is what the rest of this section covers.
2. **Server deployment** - for running it 24/7 so it keeps working even when
   your computer is off, or for a team sharing one instance. See
   [Server deployment](#server-deployment) below.

## Running it locally

**Requires:** Python 3.11+ installed once ([python.org/downloads](https://www.python.org/downloads/) -
on Windows, tick "Add Python to PATH" during install). Nothing else to
install manually - the first run does it for you.

1. Download this project's code to a folder on your computer (or `git clone` it).
2. Double-click the starter file for your operating system:
   - **Windows:** `Start PO Tracker.bat`
   - **Mac:** `Start PO Tracker.command` (right-click → Open the very first
     time, since it's not from the App Store - macOS will ask you to confirm once)
   - **Linux:** `start_po_tracker.sh`
3. The first time, a black window appears and installs everything (needs
   internet, takes 1-2 minutes). Every time after that, it starts in a few
   seconds.
4. Your browser opens automatically to the dashboard. **Create Your
   Account** the first time - that's your login from now on.
5. Click the **Settings** tab and paste in your two keys (see below for where
   to get them). Click **Save Settings**.
6. Click **+ Connect Gmail** in the bar under the header, and approve access
   with the Gmail account you want monitored.
7. In Gmail, create a filter that labels vendor emails `po-tracker` (Settings
   → Filters and Blocked Addresses → Create a new filter) - only labeled mail
   gets read.
8. Click **Run Ingestion Now** next to your connected mailbox to process
   emails on demand. Since your computer isn't running 24/7 like a server,
   this "check now" button is how Local Mode stays up to date - click it
   whenever you want the tracker refreshed.

To stop the app, close the black window (or press Ctrl+C in it). To start it
again later, just double-click the starter file again - nothing needs
reinstalling.

Everything - your database, your downloaded attachments, your saved keys - is
stored in a folder called `po_tracker_data` next to the project files. Back
that folder up if you want to keep your data safe; delete it if you ever want
to start completely fresh.

### The two keys you need (both free to set up, one has usage costs)

**Gemini API key** (free - powers the AI that reads your documents):
1. Go to **aistudio.google.com/apikey**, sign in with a Google account.
2. Click **Create API key**, copy it.
3. Google's free tier is rate-limited (a cap on requests per minute/day) but
   costs nothing - fine for personal/small-business volume.

**Google Gmail access** (lets the app read - never send or delete - your mail):
1. Go to **console.cloud.google.com**, create a project.
2. Search **Gmail API** at the top, click it, click **Enable**.
3. **APIs & Services → OAuth consent screen** → User type **External** →
   fill in the app name and your email → save through the remaining screens →
   under **Test users**, add the Gmail address you'll monitor.
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID** →
   type **Web application**.
5. Open the PO Tracker **Settings** tab first (step 5 above) to see your exact
   **Redirect URI** (with a Copy button) - paste that into **Authorized
   redirect URIs** here, then click Create.
6. Copy the **Client ID** and **Client Secret** it shows you into the PO
   Tracker Settings tab.

The first time you click **+ Connect Gmail**, Google will show a "Google
hasn't verified this app" warning - click **Advanced → Go to PO Tracker
(unsafe)**. This is normal for a private app only you use; it just means
Google hasn't reviewed it, not that anything is wrong.

**If document processing ever fails with a "model ... is no longer
available" error:** Google periodically retires older Gemini model names.
Check the error message for the replacement name it suggests, then update
the **AI Model** field in the Settings tab (below the Gemini API Key) to
that name and save - no new download needed.

## What's implemented (Phase 1 MVP, plus the Phase 2/3 matching engine)

- Gmail OAuth connection + on-demand or scheduled polling that downloads
  every supported attachment (PDF/XLS/XLSX/CSV/DOC/DOCX/JPG/PNG/TIFF).
- AI classification + structured extraction (Gemini), schema-validated before
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
- REST API (FastAPI), a dashboard (`frontend/index.html`) including a
  no-terminal first-run setup and a Settings screen for pasting API
  keys, and Excel export - Excel is a reporting format only, never the database.

## Server deployment

For a shared/always-on instance instead of Local Mode:

**Prerequisites:** Python 3.11+, PostgreSQL 14+ (or `docker-compose up -d db`),
a Google Cloud OAuth client (see above, using your real domain's redirect URI
instead of `127.0.0.1`), a Gemini API key.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-server.txt   # the second file adds the PostgreSQL driver
cp .env.example .env   # fill in DATABASE_URL and SECRET_KEY at minimum -
                        # GEMINI_API_KEY/GOOGLE_CLIENT_ID/SECRET can also be
                        # left blank here and pasted into the Settings tab instead
alembic upgrade head
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

Put the app behind HTTPS (a reverse proxy like nginx/Caddy with Let's
Encrypt), restrict CORS in `main.py` to your real domain, and run the
background worker so ingestion happens automatically all day instead of only
when someone clicks the button:

```bash
python -m backend.app.worker.tasks
```

`docker-compose.yml` runs `db` + `api` + `worker` together if you prefer
containers. `GMAIL_QUERY` (env var or Settings tab) controls which mail is
scanned (default: `label:po-tracker newer_than:7d`).

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
run_local.py              Local Mode launcher (SQLite, auto-opens browser)
Start PO Tracker.bat/.command, start_po_tracker.sh   Double-click wrappers around run_local.py
backend/app/
  models.py              SQLAlchemy models (EMAILS, DOCUMENTS, PO_MASTER, PO_LINES, GRN, ...)
  runtime_config.py       Settings that can be pasted in the dashboard instead of a .env file
  schemas.py              Pydantic schemas - the AI-output <-> DB boundary
  gmail/                  OAuth, Gmail API client, email/attachment ingestion
  extraction/             File parsers (PDF/Excel/DOCX/image) + AI classification/extraction
  validation/             Business-rule validation (never auto-corrects a value)
  matching/               Duplicate PO detection + 5-level GRN/Invoice/Note matching engine
  status/                 PO status computed from underlying transactions
  pipeline.py             Orchestrates the full per-document flow
  api/routers/            FastAPI endpoints (pos, documents, emails, exceptions, dashboard, export, search, auth, settings)
  export/                 Excel export (reporting only)
  worker/tasks.py         Scheduled Gmail polling + daily summary (optional - Local Mode uses "Run Ingestion Now" instead)
frontend/index.html       Dashboard (tracker, exceptions, vendor analysis, settings)
backend/tests/            pytest suite (AI/Gmail calls mocked)
alembic/                  DB migrations (for server deployment; Local Mode creates tables automatically)
```
