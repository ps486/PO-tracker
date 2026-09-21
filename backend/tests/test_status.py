"""Covers spec sections 9, 11, 12: status computation, partial-delivery
line-item tracking, and overdue monitoring - using the exact worked examples
from the spec."""
from datetime import date, timedelta
from decimal import Decimal

from backend.app.models import GRN, GRNLine, Invoice, POStatus
from backend.app.status.po_status import compute_po_metrics


def test_partial_delivery_line_tracking_matches_spec_example(db, make_po):
    po = make_po(
        po_number="PO-LINE", vendor_name="Acme", total_value=Decimal("1500000"),
        lines=[
            {"line_number": 1, "item_code": "A", "quantity": Decimal("1000"), "unit_price": Decimal("1000")},
            {"line_number": 2, "item_code": "B", "quantity": Decimal("500"), "unit_price": Decimal("1000")},
        ],
    )
    po_line_a, po_line_b = po.lines[0], po.lines[1]

    grn1 = GRN(po_id=po.po_id, grn_number="GRN-1")
    grn2 = GRN(po_id=po.po_id, grn_number="GRN-2")
    grn3 = GRN(po_id=po.po_id, grn_number="GRN-3")
    db.add_all([grn1, grn2, grn3])
    db.flush()

    db.add(GRNLine(grn_id=grn1.grn_id, po_line_id=po_line_a.po_line_id, received_quantity=Decimal("600"), accepted_quantity=Decimal("600")))
    db.add(GRNLine(grn_id=grn2.grn_id, po_line_id=po_line_a.po_line_id, received_quantity=Decimal("200"), accepted_quantity=Decimal("200")))
    db.add(GRNLine(grn_id=grn3.grn_id, po_line_id=po_line_b.po_line_id, received_quantity=Decimal("500"), accepted_quantity=Decimal("500")))
    db.flush()
    db.refresh(po)

    metrics = compute_po_metrics(po)

    line_a = next(l for l in metrics.line_metrics if l.item_code == "A")
    line_b = next(l for l in metrics.line_metrics if l.item_code == "B")
    assert line_a.ordered_qty == Decimal("1000")
    assert line_a.received_qty == Decimal("800")
    assert line_a.balance_qty == Decimal("200")
    assert line_b.received_qty == Decimal("500")
    assert line_b.balance_qty == Decimal("0")

    assert metrics.ordered_qty == Decimal("1500")
    assert metrics.received_qty == Decimal("1300")
    assert metrics.balance_qty == Decimal("200")
    assert metrics.computed_status == POStatus.PARTIALLY_RECEIVED


def test_fully_received_status(db, make_po):
    po = make_po(lines=[{"line_number": 1, "item_code": "A", "quantity": Decimal("1000"), "unit_price": Decimal("1")}])
    grn = GRN(po_id=po.po_id, grn_number="GRN-1")
    db.add(grn)
    db.flush()
    db.add(GRNLine(grn_id=grn.grn_id, po_line_id=po.lines[0].po_line_id, received_quantity=Decimal("1000"), accepted_quantity=Decimal("1000")))
    db.flush()
    db.refresh(po)
    metrics = compute_po_metrics(po)
    assert metrics.balance_qty == Decimal("0")
    assert metrics.computed_status == POStatus.FULLY_RECEIVED


def test_pending_delivery_status_before_any_grn(db, make_po):
    po = make_po(lines=[{"line_number": 1, "item_code": "A", "quantity": Decimal("100"), "unit_price": Decimal("1")}])
    metrics = compute_po_metrics(po)
    assert metrics.computed_status == POStatus.PENDING_DELIVERY


def test_overdue_when_expected_delivery_passed_and_balance_positive(db, make_po):
    past_date = date.today() - timedelta(days=10)
    po = make_po(
        delivery_date=past_date,
        lines=[{"line_number": 1, "item_code": "A", "quantity": Decimal("100"), "unit_price": Decimal("1")}],
    )
    metrics = compute_po_metrics(po)
    assert metrics.is_overdue
    assert metrics.days_overdue == 10
    assert metrics.computed_status == POStatus.OVERDUE


def test_not_overdue_when_fully_received_even_if_delivery_date_passed(db, make_po):
    past_date = date.today() - timedelta(days=10)
    po = make_po(delivery_date=past_date, lines=[{"line_number": 1, "item_code": "A", "quantity": Decimal("100"), "unit_price": Decimal("1")}])
    grn = GRN(po_id=po.po_id)
    db.add(grn)
    db.flush()
    db.add(GRNLine(grn_id=grn.grn_id, po_line_id=po.lines[0].po_line_id, received_quantity=Decimal("100"), accepted_quantity=Decimal("100")))
    db.flush()
    db.refresh(po)
    metrics = compute_po_metrics(po)
    assert not metrics.is_overdue
    assert metrics.computed_status == POStatus.FULLY_RECEIVED


def test_fully_invoiced_leads_to_closed(db, make_po):
    po = make_po(total_value=Decimal("1000"), lines=[{"line_number": 1, "item_code": "A", "quantity": Decimal("10"), "unit_price": Decimal("100")}])
    grn = GRN(po_id=po.po_id)
    db.add(grn)
    db.flush()
    db.add(GRNLine(grn_id=grn.grn_id, po_line_id=po.lines[0].po_line_id, received_quantity=Decimal("10"), accepted_quantity=Decimal("10")))
    db.add(Invoice(po_id=po.po_id, invoice_number="INV-1", total_value=Decimal("1000")))
    db.flush()
    db.refresh(po)
    metrics = compute_po_metrics(po)
    assert metrics.computed_status == POStatus.CLOSED


def test_manual_terminal_status_is_not_overridden(db, make_po):
    po = make_po(status=POStatus.CANCELLED, lines=[{"line_number": 1, "item_code": "A", "quantity": Decimal("10"), "unit_price": Decimal("1")}])
    metrics = compute_po_metrics(po)
    assert metrics.computed_status == POStatus.CANCELLED
