# Automated PO Tracker — System Design

This document is the pre-build design deliverable: architecture, schema, integration
approach, matching algorithm, security model, phasing, cost and required services.
The MVP (Phase 1) implemented in this repository follows this design.

## 1. System Architecture

```
                         ┌─────────────────────┐
                         │   Gmail mailbox      │
                         │ (OAuth, label/query) │
                         └──────────┬───────────┘
                                    │ Gmail API (poll / push via Pub/Sub)
                                    ▼
                   ┌───────────────────────────────┐
                   │   Ingestion Worker (scheduler)  │
                   │  - list new messages            │
                   │  - dedupe by Gmail message id    │
                   │  - persist EMAILS row            │
                   │  - download attachments          │
                   │  - hash + persist DOCUMENTS row  │
                   └──────────────┬───────────────────┘
                                  ▼
                   ┌───────────────────────────────┐
                   │   Parsing Layer                 │
                   │  PDF (pdfplumber/pymupdf)        │
                   │  Excel/CSV (openpyxl/pandas)     │
                   │  DOC/DOCX (python-docx)          │
                   │  Images/scanned PDF -> page images│
                   └──────────────┬───────────────────┘
                                  ▼
                   ┌───────────────────────────────┐
                   │  AI Classification              │
                   │  (Claude, structured JSON out)   │
                   │  -> doc type, confidence, reason │
                   └──────────────┬───────────────────┘
                                  ▼
              confidence >= threshold?  ── no ──► EXCEPTIONS queue
                                  │ yes
                                  ▼
                   ┌───────────────────────────────┐
                   │  AI Field Extraction             │
                   │  (schema-constrained JSON out)   │
                   │  header + line items             │
                   └──────────────┬───────────────────┘
                                  ▼
                   ┌───────────────────────────────┐
                   │  JSON Schema Validation          │
                   │  (pydantic, rejects malformed)   │
                   └──────────────┬───────────────────┘
                                  ▼
                   ┌───────────────────────────────┐
                   │  Business Rule Validation        │
                   │  math checks, GSTIN, duplicates  │
                   └──────────────┬───────────────────┘
                                  ▼
                validation failed / dup / low conf? ── yes ──► EXCEPTIONS queue
                                  │ no
                                  ▼
                   ┌───────────────────────────────┐
                   │  Document Router                 │
                   │  PO -> PO_MASTER + PO_LINES       │
                   │  GRN/Invoice/DN/CN -> Matching     │
                   │  Engine -> linked to PO_MASTER     │
                   └──────────────┬───────────────────┘
                                  ▼
                   ┌───────────────────────────────┐
                   │  Status Engine                   │
                   │  recompute PO status from          │
                   │  underlying transactions           │
                   └──────────────┬───────────────────┘
                                  ▼
                   ┌───────────────────────────────┐
                   │  PostgreSQL (system of record)   │
                   └──────────────┬───────────────────┘
                                  ▼
        ┌───────────────┬────────────────┬───────────────────┐
        │  REST API       │  Dashboard UI   │  Excel/CSV export  │
        │  (FastAPI)      │  (React/Next.js)│  (reporting only)  │
        └───────────────┴────────────────┴───────────────────┘
```

Design principles:
- Attachments, never email body alone, are the source of truth for structured data.
- AI output never writes to the database directly — it always passes through
  JSON-schema validation, then business-rule validation.
- Every write carries provenance: `source_email_id` / `source_document_id`, so any
  number in the tracker can be traced back to the original email + file.
- Low-confidence or inconsistent records never silently proceed — they land in
  `EXCEPTIONS` and block automatic PO/GRN/Invoice creation where risk is high
  (duplicates, ambiguous matches).
- The pipeline is idempotent: re-processing the same Gmail message id or the same
  attachment hash is a no-op (or explicitly flagged as duplicate).

## 2. Database Schema

Implemented in `backend/app/models.py` (SQLAlchemy). Entities exactly as specified:
`EMAILS`, `DOCUMENTS`, `PO_MASTER`, `PO_LINES`, `GRN`, `GRN_LINES`, `INVOICES`,
`DEBIT_CREDIT_NOTES`, `EXCEPTIONS`, plus supporting tables:

- `VENDORS` — normalized vendor master (name, GSTIN, PAN, address) so PO_MASTER can
  hold a `vendor_id` foreign key rather than free text, enabling reliable vendor
  analytics.
- `USERS` — for RBAC (Admin / Finance-CFO / Procurement / Viewer).
- `EXTRACTION_AUDIT` — one row per AI extraction attempt (raw AI JSON, confidence
  per field, model/version, timestamp) so corrected values never overwrite history.
- `AUDIT_LOG` — generic append-only log of human edits/approvals (who, what field,
  old value, new value, when) referenced from EXCEPTIONS resolution and PO edits.

All monetary/quantity fields are `NUMERIC` (not float) to avoid rounding errors.
All entities carry `created_at` / `updated_at`. Enums are used for
`document_type`, `processing_status`, `po_status`, `exception_type/severity/status`,
`note_type`.

Relationships:
- `DOCUMENTS.email_id -> EMAILS.email_id`
- `PO_MASTER.source_document_id -> DOCUMENTS.document_id`
- `PO_LINES.po_id -> PO_MASTER.po_id`
- `GRN.po_id -> PO_MASTER.po_id` (nullable until matched), `GRN_LINES.po_line_id -> PO_LINES.po_line_id`
- `INVOICES.po_id / grn_id -> PO_MASTER / GRN` (nullable until matched)
- `DEBIT_CREDIT_NOTES.po_id / invoice_id`
- `EXCEPTIONS.document_id -> DOCUMENTS.document_id`

See `backend/app/models.py` for exact columns (they mirror section 7 of the spec).

## 3. Gmail Integration Approach

- **Auth**: Google OAuth 2.0, installed/web app flow, scope
  `gmail.readonly` (+ `gmail.labels` if we want to tag processed mail). No
  passwords are ever requested. Refresh + access tokens are stored encrypted
  (Fernet, key from `SECRET_KEY` env var) in the `USERS`/`OAUTH_TOKENS` table, never
  in plaintext or in code.
- **Discovery**: Poll (`users.messages.list` with a configurable query, e.g.
  `label:po-tracker newer_than:1d`) on a scheduler interval (default 5 minutes) for
  the MVP. Documented upgrade path: Gmail push notifications via Cloud Pub/Sub
  (`users.watch`) for near-real-time ingestion in production, avoiding polling
  costs/latency.
- **Idempotency**: Gmail's `message.id` is globally unique per mailbox and is the
  primary idempotency key for EMAILS. Attachment `sha256` hash is the idempotency
  key for DOCUMENTS — the same PDF forwarded in a new email is detected as a
  duplicate attachment, not reprocessed as a new document.
- **Attachment download**: `users.messages.attachments.get`, streamed to object
  storage (local disk in MVP, S3/GCS in production) under
  `{env}/{email_id}/{attachment_hash}_{filename}`.

## 4. AI Extraction Approach

Two-stage AI calls, both **schema-constrained** (Claude "tool use" / structured
output — the model must return a specific JSON shape, no free text):

1. **Classification** (`extraction/classifier.py`): given extracted text (and, for
   scanned/image documents, the page image(s) directly via multimodal input), the
   model returns `{document_type, confidence, reasons[], extracted_document_number}`.
2. **Field extraction** (`extraction/po_extractor.py`): only runs if classification
   confidence passes the threshold; returns the full header + line-item JSON
   defined in section 4 of the spec, each field paired with a confidence score.

Pipeline enforced everywhere: **AI → JSON schema validation (pydantic) → business
rule validation → database**. A response that fails schema validation is retried
once, then routed to EXCEPTIONS as `UNREADABLE_OR_MALFORMED_EXTRACTION` — it is
never partially written.

For scanned PDFs/images we do not use a separate OCR engine as the primary path —
Claude's native document/image understanding reads the page directly, which avoids
compounding OCR errors with a second LLM pass over noisy OCR text. `pdfplumber` /
`openpyxl` / `python-docx` are used first for machine-readable files because they
are free, deterministic and higher-precision for exact numbers; the AI call still
classifies and cross-checks so a garbled table doesn't silently become a wrong PO.

The model is explicitly instructed (and this is enforced in the prompt + validated
downstream) to leave a field blank rather than infer/estimate it (section 26) —
e.g. no delivery date is invented if the document doesn't state one.

## 5. Matching Algorithm

Implemented in `matching/po_matcher.py`, in strict priority order — the first level
that produces a confident match wins; nothing below is attempted once a Level 1–2
exact match is found:

1. **Level 1 — Exact PO number**: extracted `po_number` on the GRN/Invoice/Note text
   exactly (case/whitespace-insensitive) equals an existing `PO_MASTER.po_number`.
2. **Level 2 — PO number + vendor**: PO number matches AND vendor name/GSTIN
   matches (fuzzy vendor name via token-set ratio ≥ 0.9, or exact GSTIN).
3. **Level 3 — Vendor + item + quantity + date + approximate value**: vendor
   matches, and a scoring function combines: item/SKU overlap with PO_LINES,
   quantity within tolerance, document date within the PO validity window, and
   total value within a configurable % tolerance of a PO or its remaining balance.
4. **Level 4 — Vendor + reference + email thread**: same Gmail `thread_id` as the
   PO's source email, same vendor, and a buyer/vendor reference number appears on
   both documents.
5. **Level 5 — AI/fuzzy matching**: as a last resort, the AI is given the
   candidate PO shortlist (from vendor + rough date/value filtering, never the
   whole table) and asked to pick the best match with a confidence + reasons.

Every match result is persisted as `{matched_po_id, confidence, criteria[]}`. Any
match with confidence < 90% (configurable) is **never** auto-applied — it is
written to EXCEPTIONS as `type=MULTIPLE_POSSIBLE_PO_MATCH` or
`GRN_CANNOT_BE_MATCHED`/`INVOICE_CANNOT_BE_MATCHED` with the top candidates listed
for a human to pick from.

## 6. Security Model

- **Authentication**: OAuth for Gmail access (per mailbox, per organization).
  Application users authenticate via JWT (email/password + bcrypt hash in MVP;
  SSO/OIDC is the documented production upgrade).
- **Authorization (RBAC)**, enforced in `app/security.py` and FastAPI dependencies:
  - `admin` — full access incl. mailbox connection, user management.
  - `finance` — full read, can approve/reject exceptions, view financials, export.
  - `procurement` — full read/write on PO/GRN data, can approve/reject exceptions,
    cannot manage users or mailbox connections.
  - `viewer` — read-only across tracker, dashboard, search; no exception actions.
- **Secrets**: Gmail OAuth tokens and the Anthropic API key are stored only in
  environment variables / an encrypted secrets column, never logged, never
  returned by any API response.
- **Data protection**: attachments and extracted PII (GSTIN, PAN, addresses) are
  stored in a private object store / DB, not exposed via any public URL; all API
  endpoints require authentication; audit log records every human edit and
  approval for traceability (section 15).
- **Transport**: HTTPS-only in production (TLS terminated at the load balancer/
  reverse proxy); local dev uses plain HTTP.

## 7. Development Phases

- **Phase 1 (this MVP)**: Gmail ingestion → attachment download → classification →
  PO extraction (PDF/Excel/image) → validation → duplicate detection → PO_MASTER/
  PO_LINES → PO tracker API + minimal dashboard → exception queue → Excel export.
- **Phase 2**: GRN ingestion, PO matching engine live for GRNs, quantity
  reconciliation, partial-delivery line tracking, overdue monitoring.
- **Phase 3**: Invoices, Debit/Credit Notes, financial reconciliation (received vs
  invoiced vs paid), executive dashboard with KPIs/ageing/vendor analysis, daily
  summary notifications, full RBAC + audit UI.
- **Phase 4 (future, out of scope for this build)**: extend the same
  ingest→classify→extract→match pipeline to quotations, sales orders, purchase
  invoices, payment confirmations, logistics documents — the document/extraction/
  matching layers are already generic by document type.

## 8. Estimated Running Cost (indicative, moderate volume: ~50 vendor emails/day, ~150 attachments/day)

| Component | Est. monthly cost |
|---|---|
| Postgres (managed, small instance, e.g. RDS/Cloud SQL db-f1-small) | $25–60 |
| App hosting (API + worker, 1–2 small containers) | $20–50 |
| Object storage for attachments (S3/GCS, tens of GB) | $1–5 |
| AI extraction (Claude, ~2 calls/doc avg, ~150 docs/day × 30) | $40–150 (varies with document size/pages; large scanned multi-page POs cost more per call) |
| Gmail API | Free (quota-based, no cost at this volume) |
| Misc (logging, backups, monitoring) | $10–20 |
| **Total** | **~$100–300/month** at this volume |

Cost scales primarily with AI extraction volume/document size; using
machine-readable-file fast paths (Excel/CSV/text PDF) instead of image-based calls
where possible keeps this down.

## 9. Exact APIs / Services Required

- **Gmail API** (`gmail.googleapis.com`) — OAuth 2.0 client credentials from Google
  Cloud Console (scopes: `https://www.googleapis.com/auth/gmail.readonly`).
- **Anthropic API** (Claude) — for classification + structured extraction +
  Level-5 fuzzy matching assistance. Requires `ANTHROPIC_API_KEY`.
- **PostgreSQL** — primary datastore.
- **Object storage** — local filesystem in MVP; S3/GCS/Azure Blob in production.
- **Python libraries**: `fastapi`, `sqlalchemy`, `alembic`, `pydantic`,
  `google-api-python-client` + `google-auth-oauthlib` (Gmail), `anthropic`,
  `pdfplumber`, `pymupdf` (fallback PDF rendering to images), `openpyxl`,
  `pandas`, `python-docx`, `Pillow`, `rapidfuzz` (fuzzy vendor/item matching),
  `apscheduler` (background polling worker), `openpyxl` (Excel export),
  `passlib`/`python-jose` (auth), `pytest` (tests).
- **Frontend** (later phases): React/Next.js consuming the FastAPI REST API. MVP
  ships a minimal static dashboard (`frontend/index.html`) against the same API.
