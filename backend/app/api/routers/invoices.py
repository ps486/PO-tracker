from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import Invoice
from ...security import require_viewer

router = APIRouter(prefix="/api/invoices", tags=["invoices"], dependencies=[Depends(require_viewer)])


@router.get("")
def list_invoices(po_id: str | None = None, db: Session = Depends(get_db)):
    query = db.query(Invoice)
    if po_id:
        query = query.filter(Invoice.po_id == po_id)
    invoices = query.order_by(Invoice.invoice_date.desc()).limit(200).all()
    return [
        {
            "invoice_id": i.invoice_id,
            "invoice_number": i.invoice_number,
            "invoice_date": i.invoice_date,
            "po_id": i.po_id,
            "taxable_value": i.taxable_value,
            "gst": i.gst,
            "total_value": i.total_value,
            "source_document_id": i.source_document_id,
        }
        for i in invoices
    ]
