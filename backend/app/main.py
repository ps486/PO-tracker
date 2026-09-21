from __future__ import annotations

import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .api.routers import (
    auth, dashboard, documents, emails, exceptions, export, grns, invoices, notes, pos, search, settings as settings_router,
)
from . import runtime_config
from .db import Base, SessionLocal, engine, get_db
from .gmail.client import GmailClient
from .gmail.ingest import poll_and_ingest
from .models import OAuthToken
from .config import settings
from .pipeline import process_document
from .security import require_admin

app = FastAPI(title="Automated PO Tracker", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    os.makedirs(settings.ATTACHMENT_STORAGE_DIR, exist_ok=True)
    db = SessionLocal()
    try:
        runtime_config.load_from_db(db)
    finally:
        db.close()


for router in (auth.router, emails.router, documents.router, pos.router, grns.router,
               invoices.router, notes.router, export.router, search.router, dashboard.router,
               exceptions.router, settings_router.router):
    app.include_router(router)

frontend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/dashboard", StaticFiles(directory=frontend_dir, html=True), name="dashboard")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/ingest/run", dependencies=[Depends(require_admin)])
def run_ingest_now(mailbox_email: str, db: Session = Depends(get_db)) -> dict:
    """Manually triggers one ingestion + processing cycle for the given
    connected mailbox. The scheduled worker (worker/tasks.py) does this
    automatically every GMAIL_POLL_INTERVAL_SECONDS in production."""
    token_record = (
        db.query(OAuthToken)
        .filter(OAuthToken.provider == "gmail", OAuthToken.mailbox_email == mailbox_email)
        .first()
    )
    if not token_record:
        return {"error": f"No connected Gmail mailbox for {mailbox_email}. Call /api/auth/gmail/authorize first."}

    try:
        client = GmailClient(db, token_record)
        new_documents = poll_and_ingest(db, client, runtime_config.GMAIL_QUERY)
    except Exception as exc:  # noqa: BLE001 - surface the real error to the UI instead of a silent 500
        return {"error": f"Could not read Gmail: {exc}"}

    errors = []
    for doc in new_documents:
        try:
            process_document(db, doc)
        except Exception as exc:  # noqa: BLE001 - one bad document must not lose the whole run's result
            db.rollback()
            errors.append(f"{doc.attachment_name}: {exc}")
    result = {"ingested_documents": len(new_documents)}
    if errors:
        result["error"] = "Some documents failed to process: " + "; ".join(errors)
    return result
