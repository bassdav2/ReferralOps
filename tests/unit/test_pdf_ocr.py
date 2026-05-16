from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from backend.app.core.config import get_settings
from backend.app.documents.ocr import _configure_tesseract, ocr_pdf
from backend.app.documents.parser_pdf import ParsedDocument, ParsedPage, parse_pdf


def _pdf_with_lines(path: Path, lines: list[str]) -> None:
    pdf = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    _, height = A4
    y = height - 72
    pdf.setFont("Helvetica", 11)
    for line in lines:
        pdf.drawString(72, y, line)
        y -= 20
    pdf.save()


def test_text_pdf_does_not_call_ocr(monkeypatch, tmp_path: Path):
    path = tmp_path / "text.pdf"
    _pdf_with_lines(path, ["Patient: Test Person", "Zuweisung wegen Thoraxbeschwerden."])

    def fail_ocr(*args, **kwargs):
        raise AssertionError("OCR should not run for searchable PDFs")

    monkeypatch.setattr("backend.app.documents.ocr.ocr_pdf", fail_ocr)
    monkeypatch.setenv("OCR_ENABLED", "true")
    get_settings.cache_clear()

    parsed = parse_pdf(path)

    assert "Thoraxbeschwerden" in parsed.text
    assert all(page.ocr_confidence is None for page in parsed.pages)


def test_scanned_pdf_falls_back_to_ocr(monkeypatch, tmp_path: Path):
    path = tmp_path / "scan.pdf"
    _pdf_with_lines(path, [])

    def fake_ocr(path: Path, *, languages: str, dpi: int) -> ParsedDocument:
        assert languages == "deu+eng"
        assert dpi == 300
        return ParsedDocument(
            pages=[
                ParsedPage(
                    page_number=1,
                    text="OCR erkannter Zuweisungstext",
                    ocr_confidence=0.87,
                )
            ]
        )

    monkeypatch.setattr("backend.app.documents.ocr.ocr_pdf", fake_ocr)
    monkeypatch.setenv("OCR_ENABLED", "true")
    monkeypatch.setenv("OCR_LANGUAGES", "deu+eng")
    monkeypatch.setenv("OCR_DPI", "300")
    monkeypatch.setenv("OCR_MIN_TEXT_CHARS", "24")
    get_settings.cache_clear()

    parsed = parse_pdf(path)

    assert parsed.text == "OCR erkannter Zuweisungstext"
    assert parsed.pages[0].ocr_confidence == 0.87


def test_ocr_skips_pdf_when_page_count_exceeds_limit(monkeypatch, tmp_path: Path):
    path = tmp_path / "too_many_pages.pdf"
    path.write_bytes(b"%PDF-1.4\n")

    class FakePdfDocument(list):
        def __init__(self, _path: str):
            super().__init__([object(), object()])

    monkeypatch.setitem(sys.modules, "pypdfium2", SimpleNamespace(PdfDocument=FakePdfDocument))
    monkeypatch.setitem(
        sys.modules,
        "pytesseract",
        SimpleNamespace(Output=SimpleNamespace(DICT="dict"), TesseractError=Exception),
    )
    monkeypatch.setenv("OCR_MAX_PAGES", "1")
    get_settings.cache_clear()

    parsed = ocr_pdf(path)

    assert parsed.pages[0].ocr_confidence == 0.0
    assert "limit is 1" in parsed.pages[0].text


def test_tesseract_configuration_uses_explicit_executable(monkeypatch, tmp_path: Path):
    install_dir = tmp_path / "Tesseract-OCR"
    tessdata = install_dir / "tessdata"
    tessdata.mkdir(parents=True)
    executable = install_dir / "tesseract.exe"
    executable.write_text("", encoding="utf-8")
    fake_pytesseract = SimpleNamespace(pytesseract=SimpleNamespace())

    monkeypatch.setenv("TESSERACT_CMD", str(executable))
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)

    resolved = _configure_tesseract(fake_pytesseract)

    assert resolved == executable
    assert fake_pytesseract.pytesseract.tesseract_cmd == str(executable)
    assert os.environ["TESSDATA_PREFIX"] == str(tessdata)
