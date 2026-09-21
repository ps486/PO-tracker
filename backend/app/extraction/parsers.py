"""Extracts raw text and/or page images from an attachment file so the AI layer
has something to classify/extract from.

Strategy:
  - Machine-readable PDF: extract text with pdfplumber (deterministic, free).
  - Scanned PDF (little/no extractable text): render pages to images with
    PyMuPDF and let the AI read them directly (multimodal), instead of running a
    separate OCR engine whose errors would compound into a second AI pass.
  - Excel/CSV: read every sheet/row into a text table with pandas/openpyxl -
    numbers here are exact, no AI misread risk for the raw values.
  - DOC/DOCX: paragraphs + tables via python-docx.
  - Images (jpg/png/tiff): passed to the AI directly as an image.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass, field

import pdfplumber
import pymupdf as fitz
from PIL import Image
import pandas as pd
from docx import Document as DocxDocument

MIN_TEXT_CHARS_FOR_NATIVE_PDF = 40  # below this, treat the PDF as scanned


@dataclass
class ParsedDocument:
    text: str = ""
    images: list[bytes] = field(default_factory=list)  # PNG bytes, one per page if scanned/image
    is_scanned_or_image: bool = False
    parser_error: str | None = None


def parse_file(file_path: str) -> ParsedDocument:
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == ".pdf":
            return _parse_pdf(file_path)
        if ext in (".xls", ".xlsx"):
            return _parse_excel(file_path)
        if ext == ".csv":
            return _parse_csv(file_path)
        if ext in (".doc", ".docx"):
            return _parse_docx(file_path)
        if ext in (".jpg", ".jpeg", ".png", ".tif", ".tiff"):
            return _parse_image(file_path)
        return ParsedDocument(parser_error=f"Unsupported file extension: {ext}")
    except Exception as exc:  # noqa: BLE001 - any parser failure routes to exceptions, never crashes the pipeline
        return ParsedDocument(parser_error=str(exc))


def _parse_pdf(file_path: str) -> ParsedDocument:
    text_parts: list[str] = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
            for table in page.extract_tables():
                text_parts.append(_table_to_text(table))
    full_text = "\n".join(text_parts).strip()

    if len(full_text) >= MIN_TEXT_CHARS_FOR_NATIVE_PDF:
        return ParsedDocument(text=full_text, is_scanned_or_image=False)

    # Likely scanned - render pages to images for multimodal AI reading.
    images: list[bytes] = []
    doc = fitz.open(file_path)
    try:
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            images.append(pix.tobytes("png"))
    finally:
        doc.close()
    return ParsedDocument(text=full_text, images=images, is_scanned_or_image=True)


def _parse_excel(file_path: str) -> ParsedDocument:
    sheets = pd.read_excel(file_path, sheet_name=None, dtype=str, header=None)
    parts = []
    for name, df in sheets.items():
        parts.append(f"# Sheet: {name}")
        parts.append(df.fillna("").to_csv(index=False, header=False))
    return ParsedDocument(text="\n".join(parts))


def _parse_csv(file_path: str) -> ParsedDocument:
    df = pd.read_csv(file_path, dtype=str, header=None).fillna("")
    return ParsedDocument(text=df.to_csv(index=False, header=False))


def _parse_docx(file_path: str) -> ParsedDocument:
    doc = DocxDocument(file_path)
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return ParsedDocument(text="\n".join(parts))


def _parse_image(file_path: str) -> ParsedDocument:
    with open(file_path, "rb") as f:
        raw = f.read()
    # Normalize to PNG for consistent multimodal input.
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return ParsedDocument(images=[buf.getvalue()], is_scanned_or_image=True)


def _table_to_text(table: list[list[str | None]]) -> str:
    rows = [" | ".join(cell or "" for cell in row) for row in table]
    return "\n".join(rows)
