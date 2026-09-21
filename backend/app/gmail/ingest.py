"""Turns Gmail messages into EMAILS + DOCUMENTS rows.

Idempotency (section 17):
  - EMAILS.email_id is the Gmail message id -> re-listing the same message is a
    no-op (primary key conflict avoided by checking existence first).
  - DOCUMENTS.file_hash (sha256 of attachment bytes) is checked before creating a
    new Document row -> the same attachment arriving again (forwarded, or in a
    different email) is linked as a duplicate rather than reprocessed.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Document, Email, ProcessingStatus
from .client import GmailClient, GmailMessage


def _attachment_path(email_id: str, file_hash: str, filename: str) -> str:
    directory = os.path.join(settings.ATTACHMENT_STORAGE_DIR, email_id)
    os.makedirs(directory, exist_ok=True)
    safe_name = f"{file_hash[:12]}_{filename}"
    return os.path.join(directory, safe_name)


def ingest_message(db: Session, client: GmailClient, message_id: str) -> tuple[Email, list[Document]]:
    existing_email = db.query(Email).filter(Email.email_id == message_id).first()
    if existing_email is not None:
        return existing_email, list(existing_email.documents)

    msg: GmailMessage = client.get_message(message_id)

    email_row = Email(
        email_id=msg.message_id,
        thread_id=msg.thread_id,
        sender=msg.sender,
        sender_email=msg.sender_email,
        recipient=msg.recipient,
        cc=msg.cc,
        subject=msg.subject,
        email_date=msg.email_date,
        body=msg.body,
        processed_date=datetime.utcnow(),
    )
    db.add(email_row)
    db.flush()

    documents: list[Document] = []
    for attachment in msg.attachments:
        content = client.download_attachment(msg.message_id, attachment.attachment_id)
        file_hash = hashlib.sha256(content).hexdigest()

        duplicate = db.query(Document).filter(Document.file_hash == file_hash).first()

        path = _attachment_path(msg.message_id, file_hash, attachment.filename)
        with open(path, "wb") as f:
            f.write(content)

        doc = Document(
            email_id=email_row.email_id,
            attachment_name=attachment.filename,
            attachment_size=attachment.size,
            file_hash=file_hash,
            file_location=path,
            processing_status=ProcessingStatus.DUPLICATE if duplicate else ProcessingStatus.RECEIVED,
        )
        db.add(doc)
        documents.append(doc)

    db.commit()
    for doc in documents:
        db.refresh(doc)
    db.refresh(email_row)
    return email_row, documents


def poll_and_ingest(db: Session, client: GmailClient, query: str, max_results: int = 50) -> list[Document]:
    new_documents: list[Document] = []
    for message_id in client.list_message_ids(query, max_results=max_results):
        _, docs = ingest_message(db, client, message_id)
        new_documents.extend(docs)
    return new_documents
