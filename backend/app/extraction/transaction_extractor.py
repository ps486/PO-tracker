"""AI extraction for non-PO transaction documents (GRN, Goods Receipt, Delivery
Challan, Tax Invoice, Debit Note, Credit Note). Same schema-constrained
approach as po_extractor.py - used by the matching engine (Phase 2/3).
"""
from __future__ import annotations

from ..schemas import ExtractedTransaction
from .ai_client import build_content_blocks, call_structured
from .parsers import ParsedDocument

_LINE_SCHEMA = {
    "type": "object",
    "properties": {
        "item_code": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
        "quantity": {"type": "number"},
        "accepted_quantity": {"type": ["number", "null"]},
        "rejected_quantity": {"type": ["number", "null"]},
        "unit_price": {"type": ["number", "null"]},
        "value": {"type": ["number", "null"]},
    },
    "required": ["quantity"],
}

TRANSACTION_EXTRACTION_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "document_number": {"type": ["string", "null"]},
        "document_date": {"type": ["string", "null"]},
        "vendor_name": {"type": ["string", "null"]},
        "vendor_gstin": {"type": ["string", "null"]},
        "po_number_reference": {
            "type": ["string", "null"],
            "description": "The PO number this document explicitly references, if any.",
        },
        "invoice_number_reference": {"type": ["string", "null"]},
        "buyer_reference": {"type": ["string", "null"]},
        "vendor_reference": {"type": ["string", "null"]},
        "warehouse_location": {"type": ["string", "null"]},
        "reason": {"type": ["string", "null"], "description": "Reason stated on a debit/credit note."},
        "taxable_value": {"type": ["number", "null"]},
        "gst": {"type": ["number", "null"]},
        "total_value": {"type": ["number", "null"]},
        "lines": {"type": "array", "items": _LINE_SCHEMA},
        "field_confidence": {"type": "object", "additionalProperties": {"type": "number"}},
    },
    "required": ["lines", "field_confidence"],
}

SYSTEM_PROMPT = """You are a data extraction engine for a procurement system,
extracting a GRN / Goods Receipt / Delivery Challan / Tax Invoice / Debit Note
/ Credit Note. Extract fields EXACTLY as written - never infer or estimate a
value not present in the document. If the document references a Purchase
Order number, extract it into po_number_reference verbatim. Leave any field
null if it is not explicitly stated. Provide a confidence score (0-1) for
every field you populate in field_confidence."""


def extract_transaction(parsed: ParsedDocument) -> ExtractedTransaction:
    content = build_content_blocks(parsed.text, parsed.images)
    raw = call_structured(
        SYSTEM_PROMPT, content, "transaction_extraction_result", TRANSACTION_EXTRACTION_TOOL_SCHEMA
    )
    return ExtractedTransaction.model_validate(raw)
