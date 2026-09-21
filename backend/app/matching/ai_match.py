"""Level 5 AI-assisted matching: given a short vendor-filtered shortlist of
candidate POs (never the whole table), ask the model to pick the best match.
Still schema-constrained and still subject to the same confidence threshold as
every other level - the caller in po_matcher.py decides whether to auto-apply.
"""
from __future__ import annotations

from ..models import POMaster
from ..schemas import ExtractedTransaction, MatchResult
from ..extraction.ai_client import call_structured

MATCH_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "matched_po_id": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "criteria": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["confidence", "criteria"],
}

SYSTEM_PROMPT = """You are matching an incoming GRN/Invoice/Debit-Credit Note to
the correct Purchase Order from a short candidate list. Pick the single best
match based on vendor, items, quantities, dates and values. If no candidate is
a confident match, return matched_po_id null and a low confidence. Explain your
reasoning in criteria as short bullet strings."""


def _summarize_po(po: POMaster) -> str:
    lines = "; ".join(
        f"{l.item_code or l.description or 'item'} qty={l.quantity}" for l in po.lines[:20]
    )
    return (
        f"po_id={po.po_id} po_number={po.po_number} vendor={po.vendor_name} "
        f"po_date={po.po_date} total_value={po.total_po_value} lines=[{lines}]"
    )


def _summarize_transaction(extracted: ExtractedTransaction) -> str:
    lines = "; ".join(
        f"{l.item_code or l.description or 'item'} qty={l.quantity}" for l in extracted.lines[:20]
    )
    return (
        f"document_number={extracted.document_number} vendor={extracted.vendor_name} "
        f"document_date={extracted.document_date} total_value={extracted.total_value} lines=[{lines}]"
    )


def ai_assisted_match(extracted: ExtractedTransaction, shortlist: list[POMaster]) -> MatchResult | None:
    prompt = (
        "Incoming document:\n" + _summarize_transaction(extracted) + "\n\n"
        "Candidate purchase orders:\n" + "\n".join(_summarize_po(po) for po in shortlist)
    )
    raw = call_structured(SYSTEM_PROMPT, [{"type": "text", "text": prompt}], "match_result", MATCH_TOOL_SCHEMA)
    parsed = MatchResult.model_validate({**raw, "level": 5})
    if parsed.matched_po_id and parsed.matched_po_id not in {po.po_id for po in shortlist}:
        return None  # AI hallucinated an id outside the shortlist - never trust it
    return parsed
