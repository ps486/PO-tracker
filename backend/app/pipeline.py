"""Orchestrates the full per-document pipeline (spec sections 2-9):

  parse -> classify -> (route by type) -> extract -> validate ->
  duplicate check / PO matching -> write to DB -> recompute PO status ->
  exceptions for anything below threshold or failing validation.

This module never lets AI output reach the database directly - every write is
built from a pydantic-validated `Extracted*` model, and only after
`validation/rules.py` has had a chance to flag problems (which does not block
low/medium severity issues from being recorded, but always blocks a HIGH/
CRITICAL issue or a duplicate from silently creating a new PO).
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from . import runtime_config
from .config import settings
from .extraction.classifier import classify_document
from .extraction.parsers import parse_file
from .extraction.po_extractor import extract_po
from .extraction.transaction_extractor import extract_transaction
from .matching.duplicate import check_duplicate_po
from .matching.po_matcher import is_auto_applicable, match_transaction
from .models import (
    Document,
    DocumentType,
    ExceptionRecord,
    ExceptionSeverity,
    ExceptionStatus,
    ExceptionType,
    ExtractionAudit,
    GRN,
    GRNLine,
    Invoice,
    DebitCreditNote,
    NoteType,
    POLine,
    POMaster,
    POStatus,
    ProcessingStatus,
    Vendor,
)
from .schemas import ClassificationResult, ExtractedPO, ExtractedTransaction, ValidationResult
from .status.po_status import apply_metrics, compute_po_metrics
from .validation.rules import validate_po

PO_LIKE_TYPES = {DocumentType.PURCHASE_ORDER, DocumentType.PO_AMENDMENT, DocumentType.ORDER_CONFIRMATION}
GRN_LIKE_TYPES = {DocumentType.GRN, DocumentType.GOODS_RECEIPT, DocumentType.DELIVERY_CHALLAN}
INVOICE_LIKE_TYPES = {DocumentType.TAX_INVOICE, DocumentType.PROFORMA_INVOICE}
NOTE_LIKE_TYPES = {DocumentType.DEBIT_NOTE, DocumentType.CREDIT_NOTE}


def _save_audit(db: Session, document: Document, stage: str, raw: dict, confidence: float | None) -> None:
    db.add(
        ExtractionAudit(
            document_id=document.document_id,
            stage=stage,
            model=runtime_config.AI_MODEL,
            raw_response=raw,
            overall_confidence=Decimal(str(confidence)) if confidence is not None else None,
        )
    )


def _create_exception(
    db: Session,
    document: Document | None,
    exception_type: ExceptionType | str,
    description: str,
    severity: ExceptionSeverity | str = ExceptionSeverity.MEDIUM,
    po_id: str | None = None,
    candidate_data: dict | None = None,
) -> ExceptionRecord:
    exc = ExceptionRecord(
        document_id=document.document_id if document else None,
        po_id=po_id,
        exception_type=exception_type,
        description=description,
        severity=severity,
        status=ExceptionStatus.OPEN,
        candidate_data=candidate_data,
    )
    db.add(exc)
    return exc


def _sum_or_none(*values: Decimal | None) -> Decimal | None:
    present = [v for v in values if v is not None]
    return sum(present, Decimal(0)) if present else None


def _get_or_create_vendor(db: Session, name: str | None, gstin: str | None) -> Vendor | None:
    if not name:
        return None
    normalized = name.strip().lower()
    vendor = db.query(Vendor).filter(Vendor.normalized_name == normalized).first()
    if vendor:
        if gstin and not vendor.gstin:
            vendor.gstin = gstin
        return vendor
    vendor = Vendor(name=name, normalized_name=normalized, gstin=gstin)
    db.add(vendor)
    db.flush()
    return vendor


def process_document(db: Session, document: Document) -> None:
    if document.processing_status == ProcessingStatus.DUPLICATE:
        _create_exception(
            db, document, ExceptionType.DUPLICATE_ATTACHMENT,
            "This attachment (identical file hash) has already been processed.",
            ExceptionSeverity.LOW,
        )
        db.commit()
        return

    document.processing_status = ProcessingStatus.PARSING
    parsed = parse_file(document.file_location)
    if parsed.parser_error:
        document.processing_status = ProcessingStatus.FAILED
        _create_exception(
            db, document, ExceptionType.UNREADABLE_ATTACHMENT,
            f"Could not parse attachment: {parsed.parser_error}",
            ExceptionSeverity.HIGH,
        )
        db.commit()
        return

    classification: ClassificationResult = classify_document(parsed)
    _save_audit(db, document, "classification", classification.model_dump(mode="json"), classification.confidence)

    document.document_type = DocumentType(classification.document_type)
    document.document_number = classification.extracted_document_number
    document.extraction_confidence = Decimal(str(classification.confidence))
    document.classification_reasons = classification.reasons
    document.processing_status = ProcessingStatus.CLASSIFIED

    if classification.confidence < settings.CLASSIFICATION_CONFIDENCE_THRESHOLD:
        document.processing_status = ProcessingStatus.EXCEPTION
        _create_exception(
            db, document, ExceptionType.LOW_CLASSIFICATION_CONFIDENCE,
            f"Classification confidence {classification.confidence:.0%} is below threshold "
            f"{settings.CLASSIFICATION_CONFIDENCE_THRESHOLD:.0%}. Reasons: {', '.join(classification.reasons)}",
            ExceptionSeverity.HIGH,
        )
        db.commit()
        return

    doc_type = document.document_type
    if doc_type in PO_LIKE_TYPES:
        _handle_po(db, document, parsed)
    elif doc_type in GRN_LIKE_TYPES:
        _handle_grn(db, document, parsed)
    elif doc_type in INVOICE_LIKE_TYPES:
        _handle_invoice(db, document, parsed)
    elif doc_type in NOTE_LIKE_TYPES:
        _handle_note(db, document, parsed)
    elif doc_type == DocumentType.CANCELLED_DOCUMENT:
        document.processing_status = ProcessingStatus.EXCEPTION
        _create_exception(
            db, document, ExceptionType.UNSUPPORTED_DOCUMENT,
            "Document is marked/classified as cancelled - requires manual review.",
            ExceptionSeverity.MEDIUM,
        )
    else:
        document.processing_status = ProcessingStatus.EXCEPTION
        _create_exception(
            db, document, ExceptionType.UNSUPPORTED_DOCUMENT,
            f"Document type '{doc_type.value}' is not yet auto-processed.",
            ExceptionSeverity.LOW,
        )

    db.commit()


def _handle_po(db: Session, document: Document, parsed) -> None:
    extracted: ExtractedPO = extract_po(parsed)
    _save_audit(db, document, "extraction", extracted.model_dump(mode="json"), None)

    dup = check_duplicate_po(db, extracted, document)
    if dup.is_duplicate:
        document.processing_status = ProcessingStatus.DUPLICATE
        _create_exception(
            db, document, ExceptionType.DUPLICATE_PO,
            "Possible duplicate PO: " + "; ".join(dup.reasons),
            ExceptionSeverity.HIGH,
            po_id=dup.matched_po_id,
            candidate_data={"matched_po_id": dup.matched_po_id, "reasons": dup.reasons},
        )
        return

    validation: ValidationResult = validate_po(extracted)
    blocking = [i for i in validation.issues if i.severity in ("HIGH", "CRITICAL")]
    for issue in validation.issues:
        _create_exception(db, document, issue.exception_type, issue.description, issue.severity)

    low_field_conf = [
        f for f, c in extracted.field_confidence.items() if c < settings.FIELD_CONFIDENCE_THRESHOLD
    ]
    if low_field_conf:
        _create_exception(
            db, document, ExceptionType.LOW_FIELD_CONFIDENCE,
            f"Low-confidence fields: {', '.join(low_field_conf)}",
            ExceptionSeverity.MEDIUM,
        )

    if blocking:
        document.processing_status = ProcessingStatus.EXCEPTION
        return

    po = _create_po_master(db, document, extracted)
    document.processing_status = ProcessingStatus.APPLIED

    metrics = compute_po_metrics(po)
    apply_metrics(po, metrics)


def _create_po_master(db: Session, document: Document, extracted: ExtractedPO) -> POMaster:
    vendor = _get_or_create_vendor(db, extracted.vendor_name, extracted.vendor_gstin)

    po = POMaster(
        po_number=extracted.po_number or f"UNKNOWN-{document.document_id[:8]}",
        po_date=extracted.po_date,
        vendor_id=vendor.vendor_id if vendor else None,
        vendor_name=extracted.vendor_name,
        vendor_gstin=extracted.vendor_gstin,
        vendor_pan=extracted.vendor_pan,
        vendor_address=extracted.vendor_address,
        buyer_entity=extracted.buyer_entity,
        buyer_gstin=extracted.buyer_gstin,
        ship_to=extracted.ship_to,
        bill_to=extracted.bill_to,
        currency=extracted.currency,
        payment_terms=extracted.payment_terms,
        delivery_terms=extracted.delivery_terms,
        delivery_date=extracted.expected_delivery_date,
        po_validity=extracted.po_validity,
        buyer_reference=extracted.buyer_reference,
        vendor_reference=extracted.vendor_reference,
        gross_po_value=extracted.gross_po_value,
        taxable_value=extracted.taxable_value,
        cgst=extracted.cgst,
        sgst=extracted.sgst,
        igst=extracted.igst,
        other_taxes=extracted.other_taxes,
        freight=extracted.freight,
        discount=extracted.discount,
        other_charges=extracted.other_charges,
        tax_value=_sum_or_none(extracted.cgst, extracted.sgst, extracted.igst, extracted.other_taxes),
        total_po_value=extracted.net_po_value,
        status=POStatus.PO_RECEIVED,
        source_document_id=document.document_id,
        source_email_id=document.email_id,
    )
    db.add(po)
    db.flush()

    if not extracted.line_items:
        _create_exception(
            db, document, ExceptionType.MISSING_TOTAL, "PO created without any line items.", ExceptionSeverity.HIGH
        )

    for line in extracted.line_items:
        db.add(
            POLine(
                po_id=po.po_id,
                line_number=line.line_number,
                item_code=line.item_code,
                description=line.description,
                hsn=line.hsn,
                quantity=line.quantity,
                uom=line.uom,
                unit_price=line.unit_price,
                discount=line.discount,
                tax_rate=line.tax_rate,
                tax_amount=line.tax_amount,
                line_value=line.line_value,
                expected_delivery_date=line.expected_delivery_date,
            )
        )
    db.flush()
    return po


def _handle_grn(db: Session, document: Document, parsed) -> None:
    extracted: ExtractedTransaction = extract_transaction(parsed)
    _save_audit(db, document, "extraction", extracted.model_dump(mode="json"), None)

    match = match_transaction(db, extracted, document)
    grn = GRN(
        grn_number=extracted.document_number,
        grn_date=extracted.document_date,
        po_id=match.matched_po_id if is_auto_applicable(match) else None,
        vendor=extracted.vendor_name,
        received_quantity=sum((l.quantity for l in extracted.lines), Decimal(0)) or None,
        received_value=extracted.total_value,
        warehouse_location=extracted.warehouse_location,
        source_document_id=document.document_id,
    )
    db.add(grn)
    db.flush()

    po = None
    if is_auto_applicable(match):
        po = db.query(POMaster).filter(POMaster.po_id == match.matched_po_id).first()
        po_lines_by_code = {(l.item_code or "").strip().lower(): l for l in po.lines} if po else {}
        for line in extracted.lines:
            po_line = po_lines_by_code.get((line.item_code or "").strip().lower())
            db.add(
                GRNLine(
                    grn_id=grn.grn_id,
                    po_line_id=po_line.po_line_id if po_line else None,
                    item_code=line.item_code,
                    received_quantity=line.quantity,
                    accepted_quantity=line.accepted_quantity if line.accepted_quantity is not None else line.quantity,
                    rejected_quantity=line.rejected_quantity,
                    value=line.value,
                )
            )
            if po_line and line.quantity and po_line.quantity and line.quantity > po_line.quantity:
                _create_exception(
                    db, document, ExceptionType.GRN_EXCEEDS_PO_QUANTITY,
                    f"GRN quantity {line.quantity} for item {line.item_code} exceeds PO line quantity {po_line.quantity}.",
                    ExceptionSeverity.HIGH, po_id=po.po_id,
                )
        db.flush()
        metrics = compute_po_metrics(po)
        apply_metrics(po, metrics)
        document.processing_status = ProcessingStatus.APPLIED
    else:
        document.processing_status = ProcessingStatus.EXCEPTION
        _create_exception(
            db, document,
            ExceptionType.MULTIPLE_POSSIBLE_PO_MATCH if match.alternatives else ExceptionType.GRN_CANNOT_BE_MATCHED,
            f"GRN could not be confidently matched to a PO (best confidence {match.confidence:.0%}).",
            ExceptionSeverity.HIGH,
            candidate_data={"match": match.model_dump(mode="json")},
        )


def _handle_invoice(db: Session, document: Document, parsed) -> None:
    extracted: ExtractedTransaction = extract_transaction(parsed)
    _save_audit(db, document, "extraction", extracted.model_dump(mode="json"), None)

    match = match_transaction(db, extracted, document)
    invoice = Invoice(
        invoice_number=extracted.document_number,
        invoice_date=extracted.document_date,
        po_id=match.matched_po_id if is_auto_applicable(match) else None,
        taxable_value=extracted.taxable_value,
        gst=extracted.gst,
        total_value=extracted.total_value,
        source_document_id=document.document_id,
    )
    db.add(invoice)
    db.flush()

    if is_auto_applicable(match):
        po = db.query(POMaster).filter(POMaster.po_id == match.matched_po_id).first()
        if po and po.total_po_value and extracted.total_value and extracted.total_value > po.total_po_value:
            _create_exception(
                db, document, ExceptionType.INVOICE_EXCEEDS_PO_VALUE,
                f"Invoice value {extracted.total_value} exceeds PO value {po.total_po_value}.",
                ExceptionSeverity.HIGH, po_id=po.po_id,
            )
        if po:
            metrics = compute_po_metrics(po)
            apply_metrics(po, metrics)
        document.processing_status = ProcessingStatus.APPLIED
    else:
        document.processing_status = ProcessingStatus.EXCEPTION
        _create_exception(
            db, document,
            ExceptionType.MULTIPLE_POSSIBLE_PO_MATCH if match.alternatives else ExceptionType.INVOICE_CANNOT_BE_MATCHED,
            f"Invoice could not be confidently matched to a PO (best confidence {match.confidence:.0%}).",
            ExceptionSeverity.HIGH,
            candidate_data={"match": match.model_dump(mode="json")},
        )


def _handle_note(db: Session, document: Document, parsed) -> None:
    extracted: ExtractedTransaction = extract_transaction(parsed)
    _save_audit(db, document, "extraction", extracted.model_dump(mode="json"), None)

    match = match_transaction(db, extracted, document)
    note_type = NoteType.DEBIT_NOTE if document.document_type == DocumentType.DEBIT_NOTE else NoteType.CREDIT_NOTE

    invoice = None
    if extracted.invoice_number_reference:
        invoice = db.query(Invoice).filter(Invoice.invoice_number == extracted.invoice_number_reference).first()

    note = DebitCreditNote(
        note_type=note_type,
        note_number=extracted.document_number,
        note_date=extracted.document_date,
        po_id=match.matched_po_id if is_auto_applicable(match) else None,
        invoice_id=invoice.invoice_id if invoice else None,
        reason=extracted.reason,
        taxable_value=extracted.taxable_value,
        gst=extracted.gst,
        total_value=extracted.total_value,
        source_document_id=document.document_id,
    )
    db.add(note)
    db.flush()

    if is_auto_applicable(match):
        po = db.query(POMaster).filter(POMaster.po_id == match.matched_po_id).first()
        if po:
            metrics = compute_po_metrics(po)
            apply_metrics(po, metrics)
        document.processing_status = ProcessingStatus.APPLIED
    else:
        document.processing_status = ProcessingStatus.EXCEPTION
        _create_exception(
            db, document, ExceptionType.NOTE_CANNOT_BE_MATCHED,
            f"{note_type.value} could not be confidently matched to a PO (best confidence {match.confidence:.0%}).",
            ExceptionSeverity.MEDIUM,
            candidate_data={"match": match.model_dump(mode="json")},
        )
