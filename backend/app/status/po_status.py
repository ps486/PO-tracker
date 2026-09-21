"""PO status computed purely from underlying transactions (spec section 9),
never set manually. Also implements line-item partial-delivery tracking
(section 11) and overdue monitoring (section 12).

Net Value definition used here: PO Value + Debit Notes - Credit Notes (the
spec does not give an exact formula; this is the standard procurement
convention - debit notes increase the vendor's claim, credit notes reduce it).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from ..models import NoteType, POLine, POMaster, POStatus


@dataclass
class LineMetrics:
    po_line_id: str
    item_code: str | None
    ordered_qty: Decimal
    received_qty: Decimal
    balance_qty: Decimal
    line_value: Decimal | None
    received_value: Decimal


@dataclass
class POMetrics:
    ordered_qty: Decimal
    received_qty: Decimal
    balance_qty: Decimal
    received_value: Decimal
    balance_value: Decimal
    invoice_value: Decimal
    dn_value: Decimal
    cn_value: Decimal
    net_value: Decimal
    last_transaction_date: date | None
    days_pending: int | None
    is_overdue: bool
    days_overdue: int | None
    computed_status: POStatus
    line_metrics: list[LineMetrics] = field(default_factory=list)


def _line_received(po_line: POLine) -> tuple[Decimal, Decimal]:
    received = Decimal(0)
    value = Decimal(0)
    for grn_line in po_line.grn_lines:
        qty = grn_line.accepted_quantity if grn_line.accepted_quantity is not None else grn_line.received_quantity
        received += qty or Decimal(0)
        if grn_line.value is not None:
            value += grn_line.value
        elif qty and po_line.unit_price:
            value += qty * po_line.unit_price
    return received, value


def compute_po_metrics(po: POMaster, today: date | None = None) -> POMetrics:
    today = today or datetime.utcnow().date()

    line_metrics: list[LineMetrics] = []
    ordered_qty = Decimal(0)
    received_qty = Decimal(0)
    received_value = Decimal(0)

    for po_line in po.lines:
        line_received, line_received_value = _line_received(po_line)
        line_balance = max(po_line.quantity - line_received, Decimal(0))
        line_metrics.append(
            LineMetrics(
                po_line_id=po_line.po_line_id,
                item_code=po_line.item_code,
                ordered_qty=po_line.quantity,
                received_qty=line_received,
                balance_qty=line_balance,
                line_value=po_line.line_value,
                received_value=line_received_value,
            )
        )
        ordered_qty += po_line.quantity
        received_qty += line_received
        received_value += line_received_value

    balance_qty = max(ordered_qty - received_qty, Decimal(0))
    total_po_value = po.total_po_value or Decimal(0)
    balance_value = max(total_po_value - received_value, Decimal(0))

    invoice_value = sum((inv.total_value or Decimal(0) for inv in po.invoices), Decimal(0))
    dn_value = sum(
        (n.total_value or Decimal(0) for n in po.notes if n.note_type == NoteType.DEBIT_NOTE), Decimal(0)
    )
    cn_value = sum(
        (n.total_value or Decimal(0) for n in po.notes if n.note_type == NoteType.CREDIT_NOTE), Decimal(0)
    )
    net_value = total_po_value + dn_value - cn_value

    transaction_dates = [d for d in (
        po.po_date,
        *(g.grn_date for g in po.grns),
        *(i.invoice_date for i in po.invoices),
        *(n.note_date for n in po.notes),
    ) if d is not None]
    last_transaction_date = max(transaction_dates) if transaction_dates else None

    is_overdue = bool(po.delivery_date and po.delivery_date < today and balance_qty > 0)
    days_overdue = (today - po.delivery_date).days if is_overdue and po.delivery_date else None

    days_pending = None
    if po.po_date and po.status not in (POStatus.CLOSED, POStatus.CANCELLED, POStatus.FULLY_RECEIVED):
        days_pending = (today - po.po_date).days

    computed_status = _compute_status(
        po=po,
        ordered_qty=ordered_qty,
        received_qty=received_qty,
        balance_qty=balance_qty,
        invoice_value=invoice_value,
        total_po_value=total_po_value,
        is_overdue=is_overdue,
    )

    return POMetrics(
        ordered_qty=ordered_qty,
        received_qty=received_qty,
        balance_qty=balance_qty,
        received_value=received_value,
        balance_value=balance_value,
        invoice_value=invoice_value,
        dn_value=dn_value,
        cn_value=cn_value,
        net_value=net_value,
        last_transaction_date=last_transaction_date,
        days_pending=days_pending,
        is_overdue=is_overdue,
        days_overdue=days_overdue,
        computed_status=computed_status,
        line_metrics=line_metrics,
    )


def _compute_status(
    po: POMaster,
    ordered_qty: Decimal,
    received_qty: Decimal,
    balance_qty: Decimal,
    invoice_value: Decimal,
    total_po_value: Decimal,
    is_overdue: bool,
) -> POStatus:
    # Terminal/manual statuses are never overridden by the automatic computation.
    if po.status in (POStatus.CANCELLED, POStatus.EXCEPTION, POStatus.DUPLICATE):
        return po.status

    if ordered_qty <= 0:
        return POStatus.PO_RECEIVED

    if received_qty <= 0:
        base = POStatus.PENDING_DELIVERY
    elif balance_qty > 0:
        base = POStatus.PARTIALLY_RECEIVED
    else:
        base = POStatus.FULLY_RECEIVED

    if base == POStatus.FULLY_RECEIVED and total_po_value > 0:
        if invoice_value <= 0:
            pass  # stays FULLY_RECEIVED until an invoice arrives
        elif invoice_value < total_po_value:
            base = POStatus.PARTIALLY_INVOICED
        else:
            base = POStatus.CLOSED

    if is_overdue and base in (POStatus.PENDING_DELIVERY, POStatus.PARTIALLY_RECEIVED, POStatus.PO_CONFIRMED):
        return POStatus.OVERDUE

    return base


def apply_metrics(po: POMaster, metrics: POMetrics) -> None:
    """Persists the computed status onto the PO row. Caller is responsible for
    db.commit(). Only `status` is mutated - all other metrics are derived at
    read time by compute_po_metrics() so they can never drift out of sync."""
    po.status = metrics.computed_status
