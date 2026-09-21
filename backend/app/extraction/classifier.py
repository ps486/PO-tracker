from __future__ import annotations

from ..models import DocumentType
from ..schemas import ClassificationResult
from .ai_client import build_content_blocks, call_structured
from .parsers import ParsedDocument

CLASSIFICATION_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "document_type": {"type": "string", "enum": [t.value for t in DocumentType]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "extracted_document_number": {"type": ["string", "null"]},
    },
    "required": ["document_type", "confidence", "reasons"],
}

SYSTEM_PROMPT = """You are a document classifier for a procurement system.
Classify the attached vendor document into exactly one of the allowed document
types. Base your answer ONLY on what is written in the document - never guess.
Give a confidence score (0-1) reflecting how certain you are, and list the
concrete indicators (headings, wording, layout, referenced numbers) that led to
your decision. If the document explicitly states a document number (PO number,
invoice number, GRN number, etc. - whichever applies to the type you chose),
extract it verbatim; otherwise leave it null."""


def classify_document(parsed: ParsedDocument) -> ClassificationResult:
    content = build_content_blocks(parsed.text, parsed.images)
    raw = call_structured(SYSTEM_PROMPT, content, "classification_result", CLASSIFICATION_TOOL_SCHEMA)
    return ClassificationResult.model_validate(raw)
