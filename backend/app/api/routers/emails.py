from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import Email
from ...security import require_viewer

router = APIRouter(prefix="/api/emails", tags=["emails"], dependencies=[Depends(require_viewer)])


@router.get("")
def list_emails(db: Session = Depends(get_db)):
    emails = db.query(Email).order_by(Email.email_date.desc()).limit(200).all()
    return [
        {
            "email_id": e.email_id,
            "thread_id": e.thread_id,
            "sender": e.sender,
            "subject": e.subject,
            "email_date": e.email_date,
            "attachment_count": len(e.documents),
        }
        for e in emails
    ]


@router.get("/{email_id}")
def get_email(email_id: str, db: Session = Depends(get_db)):
    email = db.query(Email).filter(Email.email_id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    return {
        "email_id": email.email_id,
        "thread_id": email.thread_id,
        "sender": email.sender,
        "sender_email": email.sender_email,
        "recipient": email.recipient,
        "cc": email.cc,
        "subject": email.subject,
        "email_date": email.email_date,
        "body": email.body,
        "documents": [
            {"document_id": d.document_id, "attachment_name": d.attachment_name, "document_type": d.document_type.value if d.document_type else None}
            for d in email.documents
        ],
    }
