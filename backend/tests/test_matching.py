"""Covers spec section 27: GRN/invoice matched to PO, multiple GRNs, no PO
reference, multiple possible matches - i.e. matching engine levels 1-5."""
from datetime import date
from decimal import Decimal

from backend.app.matching.po_matcher import is_auto_applicable, match_transaction
from backend.app.models import POLine
from backend.app.schemas import ExtractedTransaction, ExtractedTransactionLine


def _txn(**overrides):
    base = dict(document_number="GRN-1", vendor_name="Acme Supplies", document_date=date(2026, 1, 15),
                total_value=Decimal("11800"), lines=[])
    base.update(overrides)
    return ExtractedTransaction(**base)


def test_level1_po_number_only_gives_low_confidence(db, make_po, make_document):
    po = make_po(po_number="PO-1000", vendor_name="Acme Supplies")
    doc = make_document()
    result = match_transaction(db, _txn(po_number_reference="PO-1000", vendor_name="A Totally Different Vendor"), doc)
    assert result.matched_po_id == po.po_id
    assert result.level == 1
    assert not is_auto_applicable(result)  # confidence 0.80 < 0.90 threshold


def test_level2_po_number_and_vendor_match_is_auto_applicable(db, make_po, make_document):
    po = make_po(po_number="PO-1000", vendor_name="Acme Supplies")
    doc = make_document()
    result = match_transaction(db, _txn(po_number_reference="PO-1000", vendor_name="Acme Supplies"), doc)
    assert result.matched_po_id == po.po_id
    assert result.level == 2
    assert is_auto_applicable(result)


def test_level3_vendor_item_quantity_date_value_match(db, make_po, make_document):
    po = make_po(
        po_number="PO-2000", vendor_name="Acme Supplies", po_date=date(2026, 1, 1),
        total_value=Decimal("11800"),
        lines=[{"line_number": 1, "item_code": "SKU-1", "quantity": Decimal("100"), "unit_price": Decimal("100")}],
    )
    doc = make_document()
    txn = _txn(
        document_date=date(2026, 2, 1), total_value=Decimal("11800"),
        lines=[ExtractedTransactionLine(item_code="SKU-1", quantity=Decimal("100"))],
    )
    result = match_transaction(db, txn, doc)
    assert result.matched_po_id == po.po_id
    assert result.level == 3
    assert is_auto_applicable(result)


def test_level4_vendor_reference_and_thread_match(db, make_po, make_document, make_email):
    email = make_email(email_id="msg-shared", thread_id="thread-shared")
    # No po_date/total_value overlap with the incoming doc, so Level 3 can't
    # produce a (weaker, generic) match that would shadow the Level 4 check.
    po = make_po(po_number="PO-3000", vendor_name="Acme Supplies", source_email_id=email.email_id,
                 po_date=None, total_value=None)
    po.buyer_reference = "REF-123"
    db.flush()
    doc = make_document(email=email)
    txn = _txn(buyer_reference="REF-123")
    result = match_transaction(db, txn, doc)
    assert result.matched_po_id == po.po_id
    assert result.level == 4
    assert is_auto_applicable(result)


def test_grn_without_po_reference_and_no_candidates_is_unmatched(db, make_document):
    doc = make_document()
    result = match_transaction(db, _txn(vendor_name="Nobody Ever Heard Of This Vendor"), doc)
    assert result.matched_po_id is None
    assert not is_auto_applicable(result)


def test_multiple_possible_matches_are_not_auto_applied(db, make_po, make_document):
    # Two POs for the same vendor with no strong distinguishing signal -> low
    # per-candidate confidence -> must not silently pick one.
    make_po(po_number="PO-A", vendor_name="Acme Supplies", po_date=date(2026, 1, 1), total_value=Decimal("500"))
    make_po(po_number="PO-B", vendor_name="Acme Supplies", po_date=date(2026, 1, 2), total_value=Decimal("600"))
    doc = make_document()
    result = match_transaction(db, _txn(total_value=Decimal("999999")), doc)
    assert not is_auto_applicable(result)
