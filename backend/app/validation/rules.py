"""Business-rule validation for extracted PO data (spec section 5).

Duplicate detection (PO number+vendor, document hash, similar PO number, same
thread) lives in `matching/duplicate.py` since it needs DB lookups across
existing POs; this module covers everything checkable from the extracted
document alone: math consistency, format checks, and per-line sanity checks.

Per spec: "Where extraction and mathematical calculation disagree, retain the
original extracted value and flag the record for review." Nothing here ever
mutates `extracted` - it only produces issues.
"""
from __future__ import annotations

import re
from decimal import Decimal

from ..schemas import ExtractedPO, ValidationIssue, ValidationResult

GSTIN_PATTERN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}[Z]{1}[A-Z\d]{1}$")

MONEY_TOLERANCE = Decimal("1.00")  # absolute currency-unit tolerance for rounding
ABNORMAL_TAX_RATE_MAX = Decimal("40")  # % - above this is flagged, not rejected


def validate_gstin(gstin: str | None) -> bool:
    if not gstin:
        return True  # absence is a separate MISSING check, not a format failure
    return bool(GSTIN_PATTERN.match(gstin.strip().upper()))


def validate_po(extracted: ExtractedPO) -> ValidationResult:
    issues: list[ValidationIssue] = []

    if not extracted.po_number:
        issues.append(ValidationIssue(
            exception_type="PO_NUMBER_MISSING",
            description="PO number could not be found in the document.",
            severity="HIGH",
        ))

    if not extracted.po_date:
        issues.append(ValidationIssue(
            exception_type="MISSING_TOTAL",
            description="PO date is missing.",
            severity="LOW",
        ))

    if not extracted.vendor_name:
        issues.append(ValidationIssue(
            exception_type="VENDOR_MISMATCH",
            description="Vendor name could not be found in the document.",
            severity="HIGH",
        ))

    if extracted.vendor_gstin and not validate_gstin(extracted.vendor_gstin):
        issues.append(ValidationIssue(
            exception_type="INVALID_GSTIN_FORMAT",
            description=f"Vendor GSTIN '{extracted.vendor_gstin}' does not match the expected GSTIN format.",
            severity="MEDIUM",
        ))

    if extracted.buyer_gstin and not validate_gstin(extracted.buyer_gstin):
        issues.append(ValidationIssue(
            exception_type="INVALID_GSTIN_FORMAT",
            description=f"Buyer GSTIN '{extracted.buyer_gstin}' does not match the expected GSTIN format.",
            severity="MEDIUM",
        ))

    if extracted.gross_po_value is None and extracted.net_po_value is None and not extracted.line_items:
        issues.append(ValidationIssue(
            exception_type="MISSING_TOTAL",
            description="No PO total and no line items could be extracted.",
            severity="CRITICAL",
        ))

    if not extracted.line_items:
        issues.append(ValidationIssue(
            exception_type="MISSING_TOTAL",
            description="No line items were extracted from the PO.",
            severity="HIGH",
        ))

    for line in extracted.line_items:
        _validate_line(line, issues)

    _validate_grand_total(extracted, issues)

    return ValidationResult(ok=not any(i.severity in ("HIGH", "CRITICAL") for i in issues), issues=issues)


def _validate_line(line, issues: list[ValidationIssue]) -> None:
    if line.quantity is None or line.quantity <= 0:
        issues.append(ValidationIssue(
            exception_type="NEGATIVE_OR_ZERO_QUANTITY",
            description=f"Line {line.line_number}: quantity is zero or negative ({line.quantity}).",
            severity="HIGH",
        ))

    if line.tax_rate is not None and (line.tax_rate < 0 or line.tax_rate > ABNORMAL_TAX_RATE_MAX):
        issues.append(ValidationIssue(
            exception_type="ABNORMAL_TAX_RATE",
            description=f"Line {line.line_number}: tax rate {line.tax_rate}% looks abnormal.",
            severity="MEDIUM",
        ))

    if line.unit_price is not None and line.line_value is not None:
        expected = (line.quantity * line.unit_price) - (line.discount or Decimal(0))
        if abs(expected - line.line_value) > MONEY_TOLERANCE:
            issues.append(ValidationIssue(
                exception_type="PO_TOTAL_MISMATCH",
                description=(
                    f"Line {line.line_number}: quantity x unit price - discount = {expected}, "
                    f"but extracted line_value = {line.line_value}."
                ),
                severity="MEDIUM",
            ))


def _validate_grand_total(extracted: ExtractedPO, issues: list[ValidationIssue]) -> None:
    if extracted.taxable_value is None or extracted.net_po_value is None:
        return
    tax_total = sum(
        v for v in (extracted.cgst, extracted.sgst, extracted.igst, extracted.other_taxes) if v is not None
    ) or Decimal(0)
    other = sum(
        v for v in (extracted.freight, extracted.other_charges) if v is not None
    ) or Decimal(0)
    discount = extracted.discount or Decimal(0)
    expected_total = extracted.taxable_value + tax_total + other - discount
    if abs(expected_total - extracted.net_po_value) > MONEY_TOLERANCE:
        issues.append(ValidationIssue(
            exception_type="PO_TOTAL_MISMATCH",
            description=(
                f"Taxable value + taxes + other charges - discount = {expected_total}, "
                f"but extracted net PO value = {extracted.net_po_value}."
            ),
            severity="HIGH",
        ))
