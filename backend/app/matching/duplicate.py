"""Duplicate PO detection (spec section 6).

Checked, in order, before a new PO_MASTER row is created:
  1. Exact PO number + vendor match against an existing PO.
  2. Exact attachment hash match (same file already ingested as a Document).
  3. Vendor + PO date + PO value match (catches a re-typed/re-scanned PO with a
     slightly different PO number).
  4. Similar PO number for the same vendor (fuzzy string match) - catches
     typos/OCR noise in the PO number.
  5. Same Gmail thread already produced a PO.

If any check fires, the caller must NOT auto-create a second PO_MASTER row -
the document is routed to EXCEPTIONS with status DUPLICATE/REVIEW instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from ..models import Document, POMaster
from ..schemas import ExtractedPO

VALUE_TOLERANCE_PCT = Decimal("0.02")  # 2%
SIMILAR_PO_NUMBER_THRESHOLD = 85  # rapidfuzz ratio 0-100 - catches a single-character OCR/typo difference


@dataclass
class DuplicateCheckResult:
    is_duplicate: bool = False
    matched_po_id: str | None = None
    reasons: list[str] = field(default_factory=list)


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower()


def _vendor_matches(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return fuzz.token_set_ratio(_normalize(a), _normalize(b)) >= 90


def check_duplicate_po(db: Session, extracted: ExtractedPO, document: Document) -> DuplicateCheckResult:
    result = DuplicateCheckResult()

    if document.processing_status.value == "DUPLICATE":
        result.is_duplicate = True
        result.reasons.append("Attachment file hash matches a previously processed document.")

    candidates = db.query(POMaster).filter(POMaster.status != "CANCELLED").all()

    if extracted.po_number:
        for po in candidates:
            if _normalize(po.po_number) == _normalize(extracted.po_number) and _vendor_matches(
                po.vendor_name, extracted.vendor_name
            ):
                result.is_duplicate = True
                result.matched_po_id = po.po_id
                result.reasons.append(f"Exact PO number + vendor match with existing PO {po.po_number}.")

    if not result.matched_po_id and extracted.vendor_name and extracted.po_date and extracted.net_po_value:
        for po in candidates:
            if (
                _vendor_matches(po.vendor_name, extracted.vendor_name)
                and po.po_date == extracted.po_date
                and po.total_po_value is not None
                and abs(po.total_po_value - extracted.net_po_value) <= po.total_po_value * VALUE_TOLERANCE_PCT
            ):
                result.is_duplicate = True
                result.matched_po_id = po.po_id
                result.reasons.append(
                    f"Vendor + PO date + PO value match with existing PO {po.po_number}."
                )

    if not result.matched_po_id and extracted.po_number and extracted.vendor_name:
        for po in candidates:
            if _vendor_matches(po.vendor_name, extracted.vendor_name) and po.po_number:
                ratio = fuzz.ratio(_normalize(po.po_number), _normalize(extracted.po_number))
                if ratio >= SIMILAR_PO_NUMBER_THRESHOLD and ratio < 100:
                    result.is_duplicate = True
                    result.matched_po_id = po.po_id
                    result.reasons.append(
                        f"PO number '{extracted.po_number}' is very similar to existing PO '{po.po_number}' "
                        f"({ratio}% match) for the same vendor."
                    )

    if not result.matched_po_id:
        thread_id = document.email.thread_id if document.email else None
        if thread_id:
            for po in candidates:
                if po.source_email_id and po.source_email and po.source_email.thread_id == thread_id:
                    result.is_duplicate = True
                    result.matched_po_id = po.po_id
                    result.reasons.append(f"Same email thread already produced PO {po.po_number}.")

    return result
