"""Document matching engine (spec section 8): links an incoming GRN / Invoice /
Debit Note / Credit Note to the correct existing PO.

Matching priority - the first level that produces a match is used, lower levels
are not attempted once a Level 1/2 exact match exists:

  Level 1 - Exact PO number explicitly mentioned in the document.
  Level 2 - PO number + vendor both match (raises confidence over Level 1 alone).
  Level 3 - Vendor + item/SKU overlap + quantity + date + approximate value.
  Level 4 - Vendor + a shared reference number + same Gmail email thread as the PO.
  Level 5 - AI-assisted fuzzy matching over a short vendor/date/value-filtered
            candidate list (never the whole PO table).

Every result carries {matched_po_id, confidence, criteria[]}. Confidence below
MATCHING_CONFIDENCE_THRESHOLD is never auto-applied by the caller - the pipeline
must route it to EXCEPTIONS instead (spec: "Never make low-confidence automatic
matches.").
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Document, POMaster
from ..schemas import ExtractedTransaction, MatchResult, MatchSuggestion

VALUE_TOLERANCE_PCT = Decimal("0.05")
DATE_WINDOW_DAYS = 120


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower()


def _vendor_matches(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return fuzz.token_set_ratio(_normalize(a), _normalize(b)) >= 88


def match_transaction(db: Session, extracted: ExtractedTransaction, document: Document) -> MatchResult:
    candidates = db.query(POMaster).filter(POMaster.status != "CANCELLED").all()

    result = _level1_and_2(extracted, candidates)
    if result:
        return result

    result = _level3(extracted, candidates)
    if result:
        return result

    result = _level4(extracted, document, candidates)
    if result:
        return result

    return _level5_ai_assisted(extracted, candidates)


def _level1_and_2(extracted: ExtractedTransaction, candidates: list[POMaster]) -> MatchResult | None:
    if not extracted.po_number_reference:
        return None

    exact = [po for po in candidates if _normalize(po.po_number) == _normalize(extracted.po_number_reference)]
    if not exact:
        return None

    for po in exact:
        if _vendor_matches(po.vendor_name, extracted.vendor_name):
            return MatchResult(
                matched_po_id=po.po_id,
                confidence=0.98,
                level=2,
                criteria=["PO number matched", "Vendor matched"],
            )

    po = exact[0]
    return MatchResult(
        matched_po_id=po.po_id,
        confidence=0.80,
        level=1,
        criteria=["PO number matched"],
    )


def _level3(extracted: ExtractedTransaction, candidates: list[POMaster]) -> MatchResult | None:
    if not extracted.vendor_name:
        return None

    best_po: POMaster | None = None
    best_score = 0.0
    best_criteria: list[str] = []

    for po in candidates:
        if not _vendor_matches(po.vendor_name, extracted.vendor_name):
            continue

        score = 0.0
        criteria_matched = 0
        criteria = ["Vendor matched"]

        po_item_codes = {(line.item_code or "").strip().lower() for line in po.lines if line.item_code}
        doc_item_codes = {(l.item_code or "").strip().lower() for l in extracted.lines if l.item_code}
        if po_item_codes and doc_item_codes and po_item_codes & doc_item_codes:
            score += 0.30
            criteria_matched += 1
            criteria.append("Item code overlap")

        doc_qty = sum((l.quantity for l in extracted.lines), Decimal(0))
        po_qty = sum((line.quantity for line in po.lines), Decimal(0))
        if po_qty and doc_qty and abs(doc_qty - po_qty) <= po_qty * Decimal("0.2"):
            score += 0.20
            criteria_matched += 1
            criteria.append("Quantity within tolerance")

        if po.po_date and extracted.document_date:
            if po.po_date <= extracted.document_date <= po.po_date + timedelta(days=DATE_WINDOW_DAYS):
                score += 0.15
                criteria_matched += 1
                criteria.append("Document date within PO validity window")

        if po.total_po_value and extracted.total_value:
            if abs(po.total_po_value - extracted.total_value) <= po.total_po_value * VALUE_TOLERANCE_PCT:
                score += 0.25
                criteria_matched += 1
                criteria.append("Value within tolerance of PO")

        # Vendor overlap alone (or a single weak signal like "date happens to be
        # in range") is not enough to call this a Level 3 match - require at
        # least two concrete criteria so a vaguer, more specific Level 4/5
        # signal isn't shadowed by a low-quality Level 3 guess.
        if criteria_matched < 2:
            continue

        score += 0.10  # base weight for vendor match itself

        if score > best_score:
            best_score = score
            best_po = po
            best_criteria = criteria

    if best_po is None:
        return None
    return MatchResult(matched_po_id=best_po.po_id, confidence=round(best_score, 2), level=3, criteria=best_criteria)


def _level4(extracted: ExtractedTransaction, document: Document, candidates: list[POMaster]) -> MatchResult | None:
    thread_id = document.email.thread_id if document.email else None
    if not thread_id or not extracted.vendor_name:
        return None

    reference = extracted.buyer_reference or extracted.vendor_reference
    if not reference:
        return None

    for po in candidates:
        if not _vendor_matches(po.vendor_name, extracted.vendor_name):
            continue
        if po.source_email and po.source_email.thread_id == thread_id:
            po_reference = po.buyer_reference or po.vendor_reference
            if po_reference and _normalize(po_reference) == _normalize(reference):
                return MatchResult(
                    matched_po_id=po.po_id,
                    confidence=0.92,
                    level=4,
                    criteria=["Vendor matched", "Reference number matched", "Same email thread"],
                )
    return None


def _level5_ai_assisted(extracted: ExtractedTransaction, candidates: list[POMaster]) -> MatchResult:
    shortlist = [
        po for po in candidates if not extracted.vendor_name or _vendor_matches(po.vendor_name, extracted.vendor_name)
    ][:10]

    if not shortlist:
        return MatchResult(matched_po_id=None, confidence=0.0, level=5, criteria=["No candidate POs for vendor"])

    try:
        from .ai_match import ai_assisted_match  # local import: keeps AI dependency optional for tests

        suggestion = ai_assisted_match(extracted, shortlist)
    except Exception:  # noqa: BLE001 - AI failure must not crash matching; fall back to no-match
        suggestion = None

    if suggestion is None:
        return MatchResult(
            matched_po_id=None,
            confidence=0.0,
            level=5,
            criteria=["AI-assisted matching found no confident candidate"],
            alternatives=[
                MatchSuggestion(candidate_po_id=po.po_id, confidence=0.0, reasons=["Vendor match only"])
                for po in shortlist
            ],
        )
    return suggestion


def is_auto_applicable(match: MatchResult) -> bool:
    return match.matched_po_id is not None and match.confidence >= settings.MATCHING_CONFIDENCE_THRESHOLD
