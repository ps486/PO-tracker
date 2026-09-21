"""Cross-entity search (spec section 24): one query box, returns the whole
transaction chain for whatever it matches."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import Document, Email, GRN, Invoice, POLine, POMaster, DebitCreditNote
from ...security import require_viewer

router = APIRouter(prefix="/api/search", tags=["search"], dependencies=[Depends(require_viewer)])


def _po_summary(po: POMaster) -> dict:
    return {
        "type": "PO",
        "po_id": po.po_id,
        "po_number": po.po_number,
        "vendor": po.vendor_name,
        "grns": [{"grn_id": g.grn_id, "grn_number": g.grn_number} for g in po.grns],
        "invoices": [{"invoice_id": i.invoice_id, "invoice_number": i.invoice_number} for i in po.invoices],
        "notes": [{"note_id": n.note_id, "note_number": n.note_number, "note_type": n.note_type.value} for n in po.notes],
    }


@router.get("")
def search(q: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    like = f"%{q}%"
    po_ids: set[str] = set()

    for po in db.query(POMaster).filter(POMaster.po_number.ilike(like)).all():
        po_ids.add(po.po_id)
    for line in db.query(POLine).filter(POLine.item_code.ilike(like)).all():
        po_ids.add(line.po_id)
    for grn in db.query(GRN).filter(GRN.grn_number.ilike(like)).all():
        if grn.po_id:
            po_ids.add(grn.po_id)
    for inv in db.query(Invoice).filter(Invoice.invoice_number.ilike(like)).all():
        if inv.po_id:
            po_ids.add(inv.po_id)
    for note in db.query(DebitCreditNote).filter(DebitCreditNote.note_number.ilike(like)).all():
        if note.po_id:
            po_ids.add(note.po_id)
    for po in db.query(POMaster).filter(POMaster.vendor_name.ilike(like)).all():
        po_ids.add(po.po_id)

    matched_emails = db.query(Email).filter(Email.subject.ilike(like)).all()
    for email in matched_emails:
        for doc in email.documents:
            related_pos = db.query(POMaster).filter(POMaster.source_email_id == email.email_id).all()
            po_ids.update(p.po_id for p in related_pos)

    matched_documents = db.query(Document).filter(Document.document_number.ilike(like)).all()
    for doc in matched_documents:
        related_pos = db.query(POMaster).filter(POMaster.source_document_id == doc.document_id).all()
        po_ids.update(p.po_id for p in related_pos)

    pos = db.query(POMaster).filter(POMaster.po_id.in_(po_ids)).all()
    return {
        "query": q,
        "matches": [_po_summary(po) for po in pos],
        "matched_emails": [{"email_id": e.email_id, "subject": e.subject} for e in matched_emails],
    }
