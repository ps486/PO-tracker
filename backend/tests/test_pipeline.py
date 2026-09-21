"""End-to-end pipeline tests (spec section 27): standard PO creates PO_MASTER +
PO_LINES, duplicate PO is blocked, GRN against PO updates status, GRN without a
confident match is queued as an exception. AI/Gmail calls are mocked - these
tests exercise parsing -> classification -> extraction -> validation ->
duplicate/matching -> DB write -> status recompute end to end.
"""
from datetime import date
from decimal import Decimal

import pytest

from backend.app import pipeline
from backend.app.extraction.parsers import ParsedDocument
from backend.app.models import (
    DocumentType,
    ExceptionRecord,
    POMaster,
    POStatus,
    ProcessingStatus,
)
from backend.app.schemas import (
    ClassificationResult,
    ExtractedPO,
    ExtractedPOLine,
    ExtractedTransaction,
    ExtractedTransactionLine,
)


@pytest.fixture(autouse=True)
def no_real_parsing(monkeypatch):
    monkeypatch.setattr(pipeline, "parse_file", lambda path: ParsedDocument(text="dummy text"))


def test_standard_po_document_creates_po_master_and_lines(db, make_document, monkeypatch):
    doc = make_document(filename="po.pdf")

    monkeypatch.setattr(pipeline, "classify_document", lambda parsed: ClassificationResult(
        document_type="PURCHASE_ORDER", confidence=0.95, reasons=["Header says Purchase Order"],
        extracted_document_number="PO-7000",
    ))
    monkeypatch.setattr(pipeline, "extract_po", lambda parsed: ExtractedPO(
        po_number="PO-7000", po_date=date(2026, 1, 1), vendor_name="Acme Supplies",
        vendor_gstin="29ABCDE1234F1Z5", taxable_value=Decimal("1000"), cgst=Decimal("90"),
        sgst=Decimal("90"), net_po_value=Decimal("1180"),
        line_items=[ExtractedPOLine(line_number=1, item_code="SKU-1", quantity=Decimal("10"),
                                     unit_price=Decimal("100"), line_value=Decimal("1000"))],
        field_confidence={"po_number": 0.99, "vendor_name": 0.98},
    ))

    pipeline.process_document(db, doc)

    assert doc.processing_status == ProcessingStatus.APPLIED
    po = db.query(POMaster).filter(POMaster.po_number == "PO-7000").first()
    assert po is not None
    assert len(po.lines) == 1
    assert po.status == POStatus.PENDING_DELIVERY


def test_duplicate_attachment_is_never_reprocessed(db, make_document):
    doc = make_document(file_hash="dup", status=ProcessingStatus.DUPLICATE)
    pipeline.process_document(db, doc)
    exceptions = db.query(ExceptionRecord).filter(ExceptionRecord.document_id == doc.document_id).all()
    assert len(exceptions) == 1
    assert exceptions[0].exception_type.value == "DUPLICATE_ATTACHMENT"


def test_low_classification_confidence_routes_to_exception(db, make_document, monkeypatch):
    doc = make_document()
    monkeypatch.setattr(pipeline, "classify_document", lambda parsed: ClassificationResult(
        document_type="OTHER", confidence=0.40, reasons=["Illegible scan"],
    ))
    pipeline.process_document(db, doc)
    assert doc.processing_status == ProcessingStatus.EXCEPTION
    exc = db.query(ExceptionRecord).filter(ExceptionRecord.document_id == doc.document_id).first()
    assert exc.exception_type.value == "LOW_CLASSIFICATION_CONFIDENCE"


def test_duplicate_po_number_and_vendor_blocks_auto_creation(db, make_document, make_po, monkeypatch):
    make_po(po_number="PO-8000", vendor_name="Acme Supplies")
    doc = make_document()
    monkeypatch.setattr(pipeline, "classify_document", lambda parsed: ClassificationResult(
        document_type="PURCHASE_ORDER", confidence=0.95, reasons=[], extracted_document_number="PO-8000",
    ))
    monkeypatch.setattr(pipeline, "extract_po", lambda parsed: ExtractedPO(
        po_number="PO-8000", vendor_name="Acme Supplies", net_po_value=Decimal("500"),
        line_items=[ExtractedPOLine(line_number=1, quantity=Decimal("1"))],
    ))
    pipeline.process_document(db, doc)
    assert doc.processing_status == ProcessingStatus.DUPLICATE
    assert db.query(POMaster).filter(POMaster.po_number == "PO-8000").count() == 1  # still just the original
    exc = db.query(ExceptionRecord).filter(ExceptionRecord.document_id == doc.document_id).first()
    assert exc.exception_type.value == "DUPLICATE_PO"


def test_po_with_arithmetic_mismatch_is_not_auto_created(db, make_document, monkeypatch):
    doc = make_document()
    monkeypatch.setattr(pipeline, "classify_document", lambda parsed: ClassificationResult(
        document_type="PURCHASE_ORDER", confidence=0.95, reasons=[], extracted_document_number="PO-9000",
    ))
    monkeypatch.setattr(pipeline, "extract_po", lambda parsed: ExtractedPO(
        po_number="PO-9000", vendor_name="Acme Supplies", taxable_value=Decimal("1000"),
        net_po_value=Decimal("50"),  # wildly inconsistent with taxable_value
        line_items=[ExtractedPOLine(line_number=1, quantity=Decimal("1"), unit_price=Decimal("1000"), line_value=Decimal("1000"))],
    ))
    pipeline.process_document(db, doc)
    assert doc.processing_status == ProcessingStatus.EXCEPTION
    assert db.query(POMaster).filter(POMaster.po_number == "PO-9000").count() == 0
    exc = db.query(ExceptionRecord).filter(
        ExceptionRecord.document_id == doc.document_id,
        ExceptionRecord.exception_type == "PO_TOTAL_MISMATCH",
    ).first()
    assert exc is not None


def test_grn_matched_to_po_updates_status(db, make_document, make_po, monkeypatch):
    po = make_po(
        po_number="PO-GRN-1", vendor_name="Acme Supplies",
        lines=[{"line_number": 1, "item_code": "SKU-1", "quantity": Decimal("100"), "unit_price": Decimal("10")}],
    )
    doc = make_document(filename="grn.pdf")
    monkeypatch.setattr(pipeline, "classify_document", lambda parsed: ClassificationResult(
        document_type="GRN", confidence=0.95, reasons=[], extracted_document_number="GRN-1",
    ))
    monkeypatch.setattr(pipeline, "extract_transaction", lambda parsed: ExtractedTransaction(
        document_number="GRN-1", vendor_name="Acme Supplies", po_number_reference="PO-GRN-1",
        lines=[ExtractedTransactionLine(item_code="SKU-1", quantity=Decimal("100"))],
    ))
    pipeline.process_document(db, doc)

    assert doc.processing_status == ProcessingStatus.APPLIED
    db.refresh(po)
    assert po.status == POStatus.FULLY_RECEIVED


def test_grn_with_no_confident_match_is_queued_as_exception(db, make_document, monkeypatch):
    doc = make_document(filename="grn.pdf")
    monkeypatch.setattr(pipeline, "classify_document", lambda parsed: ClassificationResult(
        document_type="GRN", confidence=0.95, reasons=[], extracted_document_number="GRN-99",
    ))
    monkeypatch.setattr(pipeline, "extract_transaction", lambda parsed: ExtractedTransaction(
        document_number="GRN-99", vendor_name="Unknown Vendor Ltd", lines=[],
    ))
    pipeline.process_document(db, doc)
    assert doc.processing_status == ProcessingStatus.EXCEPTION
    exc = db.query(ExceptionRecord).filter(ExceptionRecord.document_id == doc.document_id).first()
    assert exc.exception_type.value == "GRN_CANNOT_BE_MATCHED"


def test_grn_exceeding_po_quantity_is_flagged(db, make_document, make_po, monkeypatch):
    po = make_po(
        po_number="PO-GRN-2", vendor_name="Acme Supplies",
        lines=[{"line_number": 1, "item_code": "SKU-1", "quantity": Decimal("10"), "unit_price": Decimal("10")}],
    )
    doc = make_document(filename="grn.pdf")
    monkeypatch.setattr(pipeline, "classify_document", lambda parsed: ClassificationResult(
        document_type="GRN", confidence=0.95, reasons=[], extracted_document_number="GRN-2",
    ))
    monkeypatch.setattr(pipeline, "extract_transaction", lambda parsed: ExtractedTransaction(
        document_number="GRN-2", vendor_name="Acme Supplies", po_number_reference="PO-GRN-2",
        lines=[ExtractedTransactionLine(item_code="SKU-1", quantity=Decimal("50"))],
    ))
    pipeline.process_document(db, doc)
    exc = db.query(ExceptionRecord).filter(
        ExceptionRecord.document_id == doc.document_id,
        ExceptionRecord.exception_type == "GRN_EXCEEDS_PO_QUANTITY",
    ).first()
    assert exc is not None
