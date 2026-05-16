from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class ParsedPage(BaseModel):
    page_number: int
    text: str
    ocr_confidence: float | None = None


class ParsedDocument(BaseModel):
    pages: list[ParsedPage]

    @property
    def text(self) -> str:
        return "\n\n".join(page.text for page in self.pages)


def parse_pdf(path: Path) -> ParsedDocument:
    from pypdf import PdfReader

    from backend.app.core.config import get_settings
    from backend.app.documents.ocr import ocr_pdf

    settings = get_settings()
    reader = PdfReader(str(path))
    pages: list[ParsedPage] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append(ParsedPage(page_number=index, text=text.strip()))
    parsed = ParsedDocument(pages=pages or [ParsedPage(page_number=1, text="")])
    if settings.ocr_enabled and len(parsed.text.strip()) < settings.ocr_min_text_chars:
        return ocr_pdf(path, languages=settings.ocr_languages, dpi=settings.ocr_dpi)
    return parsed


def parse_text(path: Path) -> ParsedDocument:
    return ParsedDocument(pages=[ParsedPage(page_number=1, text=path.read_text(encoding="utf-8", errors="replace"))])
