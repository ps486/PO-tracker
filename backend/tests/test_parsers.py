"""Covers spec section 27 test cases: standard PDF PO, scanned PO, image PO,
Excel PO, multi-page PDF, and unreadable attachment."""
import io
import os

import pymupdf as fitz
import openpyxl
from PIL import Image

from backend.app.extraction.parsers import parse_file


def _write_text_pdf(path: str, pages_text: list[str]) -> None:
    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page()
        page.insert_text((50, 72), text)
    doc.save(path)
    doc.close()


def _write_scanned_pdf(path: str) -> None:
    """A PDF with a drawn image and no extractable text - simulates a scan."""
    doc = fitz.open()
    page = doc.new_page()
    img = Image.new("RGB", (200, 200), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    rect = fitz.Rect(0, 0, 200, 200)
    page.insert_image(rect, stream=buf.getvalue())
    doc.save(path)
    doc.close()


def test_standard_pdf_po_extracts_text(tmp_path):
    path = str(tmp_path / "po.pdf")
    _write_text_pdf(path, ["PO Number: PO-1001\nVendor: Acme Supplies\nTotal: 11800.00"])
    result = parse_file(path)
    assert result.parser_error is None
    assert "PO-1001" in result.text
    assert result.is_scanned_or_image is False


def test_multi_page_pdf_concatenates_all_pages(tmp_path):
    path = str(tmp_path / "po_multi.pdf")
    _write_text_pdf(path, ["Page one: PO-2000", "Page two: line items follow"])
    result = parse_file(path)
    assert "PO-2000" in result.text
    assert "line items follow" in result.text


def test_scanned_pdf_falls_back_to_page_images(tmp_path):
    path = str(tmp_path / "scanned.pdf")
    _write_scanned_pdf(path)
    result = parse_file(path)
    assert result.parser_error is None
    assert result.is_scanned_or_image is True
    assert len(result.images) == 1


def test_image_po_returns_single_image(tmp_path):
    path = str(tmp_path / "po.png")
    Image.new("RGB", (100, 100), color=(0, 0, 0)).save(path)
    result = parse_file(path)
    assert result.parser_error is None
    assert result.is_scanned_or_image is True
    assert len(result.images) == 1


def test_excel_po_extracts_rows(tmp_path):
    path = str(tmp_path / "po.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["PO Number", "PO-3000"])
    ws.append(["Item", "Qty", "Price"])
    ws.append(["Widget", 10, 5.5])
    wb.save(path)
    result = parse_file(path)
    assert result.parser_error is None
    assert "PO-3000" in result.text
    assert "Widget" in result.text


def test_unreadable_attachment_returns_parser_error(tmp_path):
    path = str(tmp_path / "broken.pdf")
    with open(path, "wb") as f:
        f.write(b"this is not a real pdf file")
    result = parse_file(path)
    assert result.parser_error is not None


def test_unsupported_extension(tmp_path):
    path = str(tmp_path / "file.xyz")
    with open(path, "w") as f:
        f.write("hello")
    result = parse_file(path)
    assert result.parser_error is not None
