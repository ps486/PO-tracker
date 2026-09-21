from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...db import get_db
from ...models import POMaster
from ...security import require_viewer
from ...status.po_status import compute_po_metrics
from ...schemas import POTrackerRow

router = APIRouter(prefix="/api/pos", tags=["pos"], dependencies=[Depends(require_viewer)])


def _to_row(po: POMaster) -> POTrackerRow:
    metrics = compute_po_metrics(po)
    return POTrackerRow(
        po_id=po.po_id,
        po_number=po.po_number,
        po_date=po.po_date,
        vendor_name=po.vendor_name,
        vendor_gstin=po.vendor_gstin,
        po_value=po.total_po_value,
        expected_delivery=po.delivery_date,
        ordered_qty=metrics.ordered_qty,
        received_qty=metrics.received_qty,
        balance_qty=metrics.balance_qty,
        received_value=metrics.received_value,
        balance_value=metrics.balance_value,
        invoice_value=metrics.invoice_value,
        dn_value=metrics.dn_value,
        cn_value=metrics.cn_value,
        net_value=metrics.net_value,
        current_status=metrics.computed_status.value,
        last_transaction_date=metrics.last_transaction_date,
        days_pending=metrics.days_pending,
        exception=po.status.value == "EXCEPTION",
        source_email=po.source_email_id,
        source_document=po.source_document_id,
    )


@router.get("", response_model=list[POTrackerRow])
def list_pos(
    vendor: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    po_date_from: date | None = None,
    po_date_to: date | None = None,
    overdue_only: bool = False,
    buyer_entity: str | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(POMaster)
    if vendor:
        query = query.filter(POMaster.vendor_name.ilike(f"%{vendor}%"))
    if po_date_from:
        query = query.filter(POMaster.po_date >= po_date_from)
    if po_date_to:
        query = query.filter(POMaster.po_date <= po_date_to)
    if buyer_entity:
        query = query.filter(POMaster.buyer_entity.ilike(f"%{buyer_entity}%"))
    if min_value is not None:
        query = query.filter(POMaster.total_po_value >= min_value)
    if max_value is not None:
        query = query.filter(POMaster.total_po_value <= max_value)

    rows = [_to_row(po) for po in query.all()]

    if status_filter:
        rows = [r for r in rows if r.current_status == status_filter]
    if overdue_only:
        rows = [r for r in rows if r.current_status == "OVERDUE"]
    return rows


@router.get("/{po_id}")
def get_po_detail(po_id: str, db: Session = Depends(get_db)):
    po = db.query(POMaster).filter(POMaster.po_id == po_id).first()
    if not po:
        raise HTTPException(status_code=404, detail="PO not found")
    metrics = compute_po_metrics(po)

    timeline = []
    if po.po_date:
        timeline.append({"date": po.po_date.isoformat(), "event": f"PO {po.po_number} received"})
    for grn in po.grns:
        if grn.grn_date:
            timeline.append({"date": grn.grn_date.isoformat(), "event": f"GRN {grn.grn_number or grn.grn_id[:8]}"})
    for inv in po.invoices:
        if inv.invoice_date:
            timeline.append({"date": inv.invoice_date.isoformat(), "event": f"Invoice {inv.invoice_number or inv.invoice_id[:8]}"})
    for note in po.notes:
        if note.note_date:
            timeline.append({"date": note.note_date.isoformat(), "event": f"{note.note_type.value} {note.note_number or note.note_id[:8]}"})
    timeline.sort(key=lambda t: t["date"])

    return {
        "summary": {
            "po_id": po.po_id,
            "po_number": po.po_number,
            "vendor_name": po.vendor_name,
            "po_date": po.po_date,
            "po_value": po.total_po_value,
            "expected_delivery": po.delivery_date,
            "current_status": metrics.computed_status.value,
        },
        "quantities": {
            "ordered": metrics.ordered_qty,
            "received": metrics.received_qty,
            "balance": metrics.balance_qty,
            "invoiced_value": metrics.invoice_value,
        },
        "financials": {
            "po_value": po.total_po_value,
            "grn_value": metrics.received_value,
            "invoice_value": metrics.invoice_value,
            "dn_value": metrics.dn_value,
            "cn_value": metrics.cn_value,
            "net_value": metrics.net_value,
            "balance_value": metrics.balance_value,
        },
        "lines": [
            {
                "po_line_id": lm.po_line_id,
                "item_code": lm.item_code,
                "ordered_qty": lm.ordered_qty,
                "received_qty": lm.received_qty,
                "balance_qty": lm.balance_qty,
            }
            for lm in metrics.line_metrics
        ],
        "timeline": timeline,
        "documents": {
            "po": po.source_document_id,
            "grns": [g.source_document_id for g in po.grns],
            "invoices": [i.source_document_id for i in po.invoices],
            "notes": [n.source_document_id for n in po.notes],
            "source_email": po.source_email_id,
        },
    }
