from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import GRN
from ...security import require_viewer

router = APIRouter(prefix="/api/grns", tags=["grns"], dependencies=[Depends(require_viewer)])


@router.get("")
def list_grns(po_id: str | None = None, db: Session = Depends(get_db)):
    query = db.query(GRN)
    if po_id:
        query = query.filter(GRN.po_id == po_id)
    grns = query.order_by(GRN.grn_date.desc()).limit(200).all()
    return [
        {
            "grn_id": g.grn_id,
            "grn_number": g.grn_number,
            "grn_date": g.grn_date,
            "po_id": g.po_id,
            "vendor": g.vendor,
            "received_quantity": g.received_quantity,
            "received_value": g.received_value,
            "source_document_id": g.source_document_id,
        }
        for g in grns
    ]
