from __future__ import annotations

from ..schemas import ExtractedPO
from .ai_client import build_content_blocks, call_structured
from .parsers import ParsedDocument

_LINE_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "line_number": {"type": "integer"},
        "item_code": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
        "hsn": {"type": ["string", "null"]},
        "quantity": {"type": "number"},
        "uom": {"type": ["string", "null"]},
        "unit_price": {"type": ["number", "null"]},
        "discount": {"type": ["number", "null"]},
        "tax_rate": {"type": ["number", "null"]},
        "tax_amount": {"type": ["number", "null"]},
        "line_value": {"type": ["number", "null"]},
        "expected_delivery_date": {"type": ["string", "null"], "description": "ISO date, only if explicitly stated"},
    },
    "required": ["line_number", "quantity"],
}

PO_EXTRACTION_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "po_number": {"type": ["string", "null"]},
        "po_date": {"type": ["string", "null"]},
        "vendor_name": {"type": ["string", "null"]},
        "vendor_address": {"type": ["string", "null"]},
        "vendor_gstin": {"type": ["string", "null"]},
        "vendor_pan": {"type": ["string", "null"]},
        "buyer_entity": {"type": ["string", "null"]},
        "buyer_gstin": {"type": ["string", "null"]},
        "ship_to": {"type": ["string", "null"]},
        "bill_to": {"type": ["string", "null"]},
        "currency": {"type": ["string", "null"]},
        "payment_terms": {"type": ["string", "null"]},
        "delivery_terms": {"type": ["string", "null"]},
        "expected_delivery_date": {"type": ["string", "null"]},
        "po_validity": {"type": ["string", "null"]},
        "buyer_reference": {"type": ["string", "null"]},
        "vendor_reference": {"type": ["string", "null"]},
        "gross_po_value": {"type": ["number", "null"]},
        "taxable_value": {"type": ["number", "null"]},
        "cgst": {"type": ["number", "null"]},
        "sgst": {"type": ["number", "null"]},
        "igst": {"type": ["number", "null"]},
        "other_taxes": {"type": ["number", "null"]},
        "freight": {"type": ["number", "null"]},
        "discount": {"type": ["number", "null"]},
        "other_charges": {"type": ["number", "null"]},
        "net_po_value": {"type": ["number", "null"]},
        "line_items": {"type": "array", "items": _LINE_ITEM_SCHEMA},
        "field_confidence": {
            "type": "object",
            "description": "Map of field name -> confidence (0-1) for every header field you populated.",
            "additionalProperties": {"type": "number"},
        },
    },
    "required": ["line_items", "field_confidence"],
}

SYSTEM_PROMPT = """You are a purchase-order data extraction engine for a
procurement system. Extract structured fields from the attached Purchase
Order document EXACTLY as written.

Rules (critical, non-negotiable):
1. Never infer, estimate, or default a value that is not explicitly present in
   the document. If a field (e.g. expected delivery date, payment terms,
   vendor GSTIN) is not stated, return null for it. Do NOT compute a plausible
   date or number.
2. Extract every line item separately - never collapse multiple lines into a
   total.
3. Use the numbers exactly as printed - do not round, adjust, or "correct"
   what looks like an inconsistency; extraction should mirror the source.
4. Dates must be returned as ISO 8601 (YYYY-MM-DD) only if a date is
   unambiguously stated.
5. For every header field you populate, include a confidence score (0-1) in
   field_confidence reflecting how legible/unambiguous that value was in the
   source document."""


def extract_po(parsed: ParsedDocument) -> ExtractedPO:
    content = build_content_blocks(parsed.text, parsed.images)
    raw = call_structured(
        SYSTEM_PROMPT, content, "po_extraction_result", PO_EXTRACTION_TOOL_SCHEMA, max_tokens=8192
    )
    return ExtractedPO.model_validate(raw)
