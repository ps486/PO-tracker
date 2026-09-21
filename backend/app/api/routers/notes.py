from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import DebitCreditNote
from ...security import require_viewer

router = APIRouter(prefix="/api/notes", tags=["notes"], dependencies=[Depends(require_viewer)])


@router.get("")
def list_notes(po_id: str | None = None, note_type: str | None = None, db: Session = Depends(get_db)):
    query = db.query(DebitCreditNote)
    if po_id:
        query = query.filter(DebitCreditNote.po_id == po_id)
    if note_type:
        query = query.filter(DebitCreditNote.note_type == note_type)
    notes = query.order_by(DebitCreditNote.note_date.desc()).limit(200).all()
    return [
        {
            "note_id": n.note_id,
            "note_type": n.note_type.value,
            "note_number": n.note_number,
            "note_date": n.note_date,
            "po_id": n.po_id,
            "invoice_id": n.invoice_id,
            "reason": n.reason,
            "total_value": n.total_value,
            "source_document_id": n.source_document_id,
        }
        for n in notes
    ]
