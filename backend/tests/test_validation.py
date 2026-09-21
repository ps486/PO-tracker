"""Covers spec section 27 test cases: PO with missing PO number, arithmetic
mismatch, negative/zero quantity, abnormal tax rate, invalid GSTIN."""
from decimal import Decimal

from backend.app.schemas import ExtractedPO, ExtractedPOLine
from backend.app.validation.rules import validate_gstin, validate_po


def _valid_line(**overrides):
    base = dict(
        line_number=1, item_code="SKU-1", description="Widget", quantity=Decimal("10"),
        unit_price=Decimal("100"), discount=Decimal("0"), tax_rate=Decimal("18"),
        tax_amount=Decimal("180"), line_value=Decimal("1180"),
    )
    base.update(overrides)
    return ExtractedPOLine(**base)


def _valid_po(**overrides):
    base = dict(
        po_number="PO-1001", vendor_name="Acme Supplies", vendor_gstin="29ABCDE1234F1Z5",
        taxable_value=Decimal("1000"), cgst=Decimal("90"), sgst=Decimal("90"),
        net_po_value=Decimal("1180"), line_items=[_valid_line()],
    )
    base.update(overrides)
    return ExtractedPO(**base)


def test_valid_po_passes_validation():
    result = validate_po(_valid_po())
    assert result.ok
    assert not any(i.severity in ("HIGH", "CRITICAL") for i in result.issues)


def test_missing_po_number_is_flagged():
    result = validate_po(_valid_po(po_number=None))
    assert not result.ok
    assert any(i.exception_type == "PO_NUMBER_MISSING" for i in result.issues)


def test_line_arithmetic_mismatch_is_flagged():
    bad_line = _valid_line(line_value=Decimal("999999"))
    result = validate_po(_valid_po(line_items=[bad_line]))
    assert any(i.exception_type == "PO_TOTAL_MISMATCH" for i in result.issues)


def test_grand_total_arithmetic_mismatch_is_flagged():
    result = validate_po(_valid_po(net_po_value=Decimal("50")))
    assert not result.ok
    assert any(i.exception_type == "PO_TOTAL_MISMATCH" and i.severity == "HIGH" for i in result.issues)


def test_extraction_value_is_never_silently_corrected():
    po = _valid_po(net_po_value=Decimal("50"))
    validate_po(po)
    assert po.net_po_value == Decimal("50")  # original extracted value is untouched


def test_negative_or_zero_quantity_is_flagged():
    result = validate_po(_valid_po(line_items=[_valid_line(quantity=Decimal("0"))]))
    assert any(i.exception_type == "NEGATIVE_OR_ZERO_QUANTITY" for i in result.issues)

    result_negative = validate_po(_valid_po(line_items=[_valid_line(quantity=Decimal("-5"))]))
    assert any(i.exception_type == "NEGATIVE_OR_ZERO_QUANTITY" for i in result_negative.issues)


def test_abnormal_tax_rate_is_flagged():
    result = validate_po(_valid_po(line_items=[_valid_line(tax_rate=Decimal("85"))]))
    assert any(i.exception_type == "ABNORMAL_TAX_RATE" for i in result.issues)


def test_invalid_gstin_format_is_flagged():
    result = validate_po(_valid_po(vendor_gstin="INVALID-GSTIN"))
    assert any(i.exception_type == "INVALID_GSTIN_FORMAT" for i in result.issues)
    assert validate_gstin("29ABCDE1234F1Z5") is True
    assert validate_gstin("INVALID-GSTIN") is False
    assert validate_gstin(None) is True


def test_missing_line_items_is_flagged():
    result = validate_po(_valid_po(line_items=[]))
    assert not result.ok
    assert any(i.exception_type == "MISSING_TOTAL" for i in result.issues)
