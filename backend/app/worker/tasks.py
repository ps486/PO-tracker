"""Background worker (spec section 18: "no manual Excel entry" - new emails are
picked up automatically throughout the day).

Runs two scheduled jobs:
  - poll_all_mailboxes: every GMAIL_POLL_INTERVAL_SECONDS, lists new messages
    for every connected Gmail mailbox and runs them through the full pipeline.
  - daily_summary: once a day, logs the summary described in spec section 19.
    (Emailing/pushing it to a dashboard notification channel is a documented
    follow-up - this MVP prints the same numbers the /api/dashboard/daily-summary
    endpoint returns, so any channel can be wired to it later without touching
    the calculation logic.)
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from .. import runtime_config
from ..config import settings
from ..db import SessionLocal
from ..gmail.client import GmailClient
from ..gmail.ingest import poll_and_ingest
from ..models import OAuthToken
from ..pipeline import process_document

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("po_tracker.worker")


def poll_all_mailboxes() -> None:
    db = SessionLocal()
    try:
        tokens = db.query(OAuthToken).filter(OAuthToken.provider == "gmail").all()
        for token_record in tokens:
            try:
                client = GmailClient(db, token_record)
                new_documents = poll_and_ingest(db, client, runtime_config.GMAIL_QUERY)
                for doc in new_documents:
                    process_document(db, doc)
                logger.info("Processed %d new document(s) for %s", len(new_documents), token_record.mailbox_email)
            except Exception:  # noqa: BLE001 - one mailbox failing must not stop the others
                logger.exception("Failed to poll mailbox %s", token_record.mailbox_email)
    finally:
        db.close()


def daily_summary() -> None:
    from ..api.routers.dashboard import daily_summary as compute_summary

    db = SessionLocal()
    try:
        summary = compute_summary(db)
        logger.info("Daily summary: %s", summary)
    finally:
        db.close()


def main() -> None:
    db = SessionLocal()
    try:
        runtime_config.load_from_db(db)  # this is a separate process from the API - settings saved via the dashboard live in the DB, not this process's env vars
    finally:
        db.close()

    scheduler = BlockingScheduler()
    scheduler.add_job(poll_all_mailboxes, "interval", seconds=settings.GMAIL_POLL_INTERVAL_SECONDS, id="poll_gmail")
    scheduler.add_job(daily_summary, "cron", hour=18, minute=0, id="daily_summary")
    logger.info("Worker started: polling every %ds", settings.GMAIL_POLL_INTERVAL_SECONDS)
    scheduler.start()


if __name__ == "__main__":
    main()
