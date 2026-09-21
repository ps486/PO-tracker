"""Covers spec section 27: duplicate PO detection (section 6)."""
from datetime import date
from decimal import Decimal

from backend.app.matching.duplicate import check_duplicate_po
from backend.app.models import ProcessingStatus
from backend.app.schemas import ExtractedPO


def _extracted(**overrides):
    base = dict(po_number="PO-1000", vendor_name="Acme Supplies", po_date=date(2026, 1, 1), net_po_value=Decimal("11800"))
    base.update(overrides)
    return ExtractedPO(**base)


def test_exact_po_number_and_vendor_is_duplicate(db, make_po, make_document):
    make_po(po_number="PO-1000", vendor_name="Acme Supplies")
    doc = make_document(file_hash="new-hash")
    result = check_duplicate_po(db, _extracted(), doc)
    assert result.is_duplicate
    assert "PO number + vendor" in result.reasons[0]


def test_different_vendor_same_po_number_is_not_duplicate(db, make_po, make_document):
    make_po(po_number="PO-1000", vendor_name="Totally Different Vendor Ltd")
    doc = make_document(file_hash="new-hash")
    result = check_duplicate_po(db, _extracted(vendor_name="Acme Supplies"), doc)
    assert not result.is_duplicate


def test_vendor_date_value_match_is_duplicate(db, make_po, make_document):
    make_po(po_number="PO-9999-DIFFERENT", vendor_name="Acme Supplies", po_date=date(2026, 1, 1), total_value=Decimal("11800"))
    doc = make_document(file_hash="new-hash")
    result = check_duplicate_po(db, _extracted(po_number="PO-0001"), doc)
    assert result.is_duplicate


def test_similar_po_number_same_vendor_is_flagged(db, make_po, make_document):
    make_po(po_number="PO-10000", vendor_name="Acme Supplies", po_date=date(2020, 1, 1), total_value=Decimal("500"))
    doc = make_document(file_hash="new-hash")
    # Single OCR-style digit swap (0 -> O) - should still be caught as "very similar".
    result = check_duplicate_po(db, _extracted(po_number="PO-1000O", net_po_value=Decimal("999999")), doc)
    assert result.is_duplicate


def test_same_email_thread_already_produced_po_is_flagged(db, make_po, make_document, make_email):
    email = make_email(email_id="msg-shared", thread_id="thread-shared")
    make_po(po_number="PO-5555", vendor_name="Acme Supplies", source_email_id=email.email_id)
    doc = make_document(email=email, file_hash="new-hash")
    result = check_duplicate_po(db, _extracted(po_number="PO-DIFFERENT", vendor_name="Acme Supplies"), doc)
    assert result.is_duplicate


def test_duplicate_attachment_hash_is_flagged(db, make_document):
    doc = make_document(file_hash="dup-hash", status=ProcessingStatus.DUPLICATE)
    result = check_duplicate_po(db, _extracted(), doc)
    assert result.is_duplicate


def test_unrelated_po_is_not_duplicate(db, make_po, make_document):
    make_po(po_number="PO-1", vendor_name="Someone Else", po_date=date(2020, 1, 1), total_value=Decimal("1"))
    doc = make_document(file_hash="new-hash")
    result = check_duplicate_po(db, _extracted(po_number="PO-9999", vendor_name="Brand New Vendor"), doc)
    assert not result.is_duplicate
