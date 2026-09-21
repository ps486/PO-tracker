"""Pydantic schemas.

Two purposes:
1. Schema-constrained AI output (classification + extraction) - the AI's raw JSON
   is parsed into these models and REJECTED if it doesn't validate. This is the
   enforced boundary between "AI said" and "database has".
2. API request/response models.

Per spec section 26: a field that isn't stated in the source document must be
left None, never inferred/estimated - reflected by making almost every business
field Optional with no default value substitution.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# AI classification output
# ---------------------------------------------------------------------------

class ClassificationResult(BaseModel):
    document_type: str
    confidence: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)
    extracted_document_number: Optional[str] = None

    @field_validator("document_type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        from .models import DocumentType  # avoid circular import at module load

        valid = {t.value for t in DocumentType}
        if v not in valid:
            raise ValueError(f"document_type must be one of {valid}, got {v!r}")
        return v


# ---------------------------------------------------------------------------
# AI PO extraction output
# ---------------------------------------------------------------------------

class FieldConfidence(BaseModel):
    """Per-field confidence, keyed by field name -> score, returned alongside data."""
    scores: dict[str, float] = Field(default_factory=dict)


class ExtractedPOLine(BaseModel):
    line_number: int
    item_code: Optional[str] = None
    description: Optional[str] = None
    hsn: Optional[str] = None
    quantity: Decimal
    uom: Optional[str] = None
    unit_price: Optional[Decimal] = None
    discount: Optional[Decimal] = None
    tax_rate: Optional[Decimal] = None
    tax_amount: Optional[Decimal] = None
    line_value: Optional[Decimal] = None
    expected_delivery_date: Optional[date] = None


class ExtractedPO(BaseModel):
    po_number: Optional[str] = None
    po_date: Optional[date] = None
    vendor_name: Optional[str] = None
    vendor_address: Optional[str] = None
    vendor_gstin: Optional[str] = None
    vendor_pan: Optional[str] = None
    buyer_entity: Optional[str] = None
    buyer_gstin: Optional[str] = None
    ship_to: Optional[str] = None
    bill_to: Optional[str] = None
    currency: Optional[str] = None
    payment_terms: Optional[str] = None
    delivery_terms: Optional[str] = None
    expected_delivery_date: Optional[date] = None
    po_validity: Optional[date] = None
    buyer_reference: Optional[str] = None
    vendor_reference: Optional[str] = None

    gross_po_value: Optional[Decimal] = None
    taxable_value: Optional[Decimal] = None
    cgst: Optional[Decimal] = None
    sgst: Optional[Decimal] = None
    igst: Optional[Decimal] = None
    other_taxes: Optional[Decimal] = None
    freight: Optional[Decimal] = None
    discount: Optional[Decimal] = None
    other_charges: Optional[Decimal] = None
    net_po_value: Optional[Decimal] = None

    line_items: list[ExtractedPOLine] = Field(default_factory=list)
    field_confidence: dict[str, float] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# AI extraction output for GRN / Invoice / Debit-Credit Note (generic
# "transaction document" shape - Phase 2/3, but designed now so the pipeline
# can route to it without a schema change later).
# ---------------------------------------------------------------------------

class ExtractedTransactionLine(BaseModel):
    item_code: Optional[str] = None
    description: Optional[str] = None
    quantity: Decimal
    accepted_quantity: Optional[Decimal] = None
    rejected_quantity: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None
    value: Optional[Decimal] = None


class ExtractedTransaction(BaseModel):
    document_number: Optional[str] = None
    document_date: Optional[date] = None
    vendor_name: Optional[str] = None
    vendor_gstin: Optional[str] = None
    po_number_reference: Optional[str] = None
    invoice_number_reference: Optional[str] = None
    buyer_reference: Optional[str] = None
    vendor_reference: Optional[str] = None
    warehouse_location: Optional[str] = None
    reason: Optional[str] = None
    taxable_value: Optional[Decimal] = None
    gst: Optional[Decimal] = None
    total_value: Optional[Decimal] = None
    lines: list[ExtractedTransactionLine] = Field(default_factory=list)
    field_confidence: dict[str, float] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# AI matching assistance (Level 5)
# ---------------------------------------------------------------------------

class MatchSuggestion(BaseModel):
    candidate_po_id: str
    confidence: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)


class MatchResult(BaseModel):
    matched_po_id: Optional[str] = None
    confidence: float = Field(ge=0, le=1, default=0.0)
    criteria: list[str] = Field(default_factory=list)
    level: Optional[int] = None
    alternatives: list[MatchSuggestion] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

class ValidationIssue(BaseModel):
    exception_type: str
    description: str
    severity: str = "MEDIUM"


class ValidationResult(BaseModel):
    ok: bool
    issues: list[ValidationIssue] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API: PO tracker row (section 10)
# ---------------------------------------------------------------------------

class POTrackerRow(BaseModel):
    po_id: str
    po_number: str
    po_date: Optional[date]
    vendor_name: Optional[str]
    vendor_gstin: Optional[str]
    po_value: Optional[Decimal]
    expected_delivery: Optional[date]
    ordered_qty: Decimal
    received_qty: Decimal
    balance_qty: Decimal
    received_value: Decimal
    balance_value: Decimal
    invoice_value: Decimal
    dn_value: Decimal
    cn_value: Decimal
    net_value: Decimal
    current_status: str
    last_transaction_date: Optional[date]
    days_pending: Optional[int]
    exception: bool
    source_email: Optional[str]
    source_document: Optional[str]

    model_config = {"from_attributes": True}


class ExceptionOut(BaseModel):
    exception_id: str
    document_id: Optional[str]
    po_id: Optional[str]
    exception_type: str
    description: Optional[str]
    severity: str
    status: str
    candidate_data: Optional[dict] = None
    assigned_to: Optional[str]
    resolution: Optional[str]

    model_config = {"from_attributes": True}


class ExceptionResolveRequest(BaseModel):
    action: str  # APPROVE | REJECT
    resolution: Optional[str] = None
    correct_po_id: Optional[str] = None
    field_corrections: Optional[dict] = None


class DashboardKPIs(BaseModel):
    total_pos: int
    total_po_value: Decimal
    open_pos: int
    closed_pos: int
    overdue_pos: int
    pending_delivery_value: Decimal
    received_value: Decimal
    pending_invoice_value: Decimal
    exceptions: int
    duplicate_pos: int
