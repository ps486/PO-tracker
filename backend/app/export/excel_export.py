"""Excel export (spec section 21: Excel is a reporting format, never the
primary datastore - this module only ever reads from Postgres and writes a
throwaway .xlsx)."""
from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy.orm import Session

from ..models import POMaster
from ..status.po_status import compute_po_metrics

HEADERS = [
    "PO Number", "PO Date", "Vendor", "Vendor GSTIN", "PO Value", "Expected Delivery",
    "Ordered Qty", "Received Qty", "Balance Qty", "Received Value", "Balance Value",
    "Invoice Value", "DN Value", "CN Value", "Net Value", "Current Status",
    "Last Transaction Date", "Days Pending", "Source Email", "Source Document",
]


def export_po_tracker(db: Session) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "PO Tracker"
    ws.append(HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for po in db.query(POMaster).all():
        m = compute_po_metrics(po)
        ws.append([
            po.po_number, po.po_date, po.vendor_name, po.vendor_gstin,
            float(po.total_po_value) if po.total_po_value is not None else None,
            po.delivery_date,
            float(m.ordered_qty), float(m.received_qty), float(m.balance_qty),
            float(m.received_value), float(m.balance_value), float(m.invoice_value),
            float(m.dn_value), float(m.cn_value), float(m.net_value),
            m.computed_status.value, m.last_transaction_date, m.days_pending,
            po.source_email_id, po.source_document_id,
        ])

    for col in ws.columns:
        max_len = max((len(str(c.value)) for c in col if c.value is not None), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 40)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
