from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.documents.parser_pdf import ParsedDocument, ParsedPage


def ocr_stub(path: Path, reason: str | None = None) -> ParsedDocument:
    message = f"OCR is not available for {path.name}. Human review required."
    if reason:
        message = f"{message} Reason: {reason}"
    return ParsedDocument(
        pages=[
            ParsedPage(
                page_number=1,
                text=message,
                ocr_confidence=0.0,
            )
        ]
    )


def _mean_confidence(data: dict) -> float | None:
    values: list[float] = []
    for raw in data.get("conf", []):
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            values.append(value)
    if not values:
        return None
    return sum(values) / len(values) / 100


def _candidate_tesseract_paths() -> list[Path]:
    candidates: list[Path] = []
    env_cmd = os.getenv("TESSERACT_CMD")
    if env_cmd:
        candidates.append(Path(env_cmd))

    path_cmd = shutil.which("tesseract")
    if path_cmd:
        candidates.append(Path(path_cmd))

    for root in (
        os.getenv("ProgramFiles"),
        os.getenv("ProgramFiles(x86)"),
        os.getenv("LOCALAPPDATA"),
    ):
        if root:
            candidates.append(Path(root) / "Tesseract-OCR" / "tesseract.exe")
            candidates.append(Path(root) / "Programs" / "Tesseract-OCR" / "tesseract.exe")

    candidates.extend(
        [
            Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
            Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"),
            Path("C:/ProgramData/chocolatey/bin/tesseract.exe"),
            Path("/opt/homebrew/bin/tesseract"),
            Path("/usr/local/bin/tesseract"),
            Path("/usr/bin/tesseract"),
        ]
    )

    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def _configure_tesseract(pytesseract_module) -> Path | None:
    for candidate in _candidate_tesseract_paths():
        if candidate.is_file():
            target = getattr(pytesseract_module, "pytesseract", pytesseract_module)
            target.tesseract_cmd = str(candidate)
            tessdata = candidate.parent / "tessdata"
            if tessdata.is_dir() and not os.getenv("TESSDATA_PREFIX"):
                os.environ["TESSDATA_PREFIX"] = str(tessdata)
            return candidate
    return None


def ocr_pdf(path: Path, *, languages: str = "deu+eng", dpi: int = 200) -> ParsedDocument:
    try:
        import pypdfium2 as pdfium
        import pytesseract
    except ImportError as exc:
        return ocr_stub(path, f"missing OCR dependency: {exc.name}")

    try:
        pdf = pdfium.PdfDocument(str(path))
    except Exception as exc:
        return ocr_stub(path, f"could not render PDF: {exc}")

    settings = get_settings()
    page_count = len(pdf)
    if page_count > settings.ocr_max_pages:
        return ocr_stub(
            path,
            f"OCR skipped because PDF has {page_count} pages; limit is {settings.ocr_max_pages}.",
        )
    if _configure_tesseract(pytesseract) is None:
        return ocr_stub(
            path,
            "tesseract executable not found. Install Tesseract OCR or set TESSERACT_CMD.",
        )

    pages: list[ParsedPage] = []
    scale = dpi / 72
    started_at = time.monotonic()
    for index, page in enumerate(pdf, start=1):
        if time.monotonic() - started_at > settings.ocr_total_timeout_seconds:
            pages.append(
                ParsedPage(
                    page_number=index,
                    text=(
                        f"OCR skipped for page {index} of {path.name}. Human review required. "
                        f"Reason: total OCR timeout exceeded {settings.ocr_total_timeout_seconds:.0f}s."
                    ),
                    ocr_confidence=0.0,
                )
            )
            break
        try:
            width, height = page.get_size()
            rendered_pixels = int(width * scale) * int(height * scale)
            if rendered_pixels > settings.ocr_max_pixels_per_page:
                pages.append(
                    ParsedPage(
                        page_number=index,
                        text=(
                            f"OCR skipped for page {index} of {path.name}. Human review required. "
                            f"Reason: rendered page would have {rendered_pixels} pixels; "
                            f"limit is {settings.ocr_max_pixels_per_page}."
                        ),
                        ocr_confidence=0.0,
                    )
                )
                continue
            image = page.render(scale=scale).to_pil().convert("L")
            text = pytesseract.image_to_string(
                image,
                lang=languages,
                timeout=settings.ocr_page_timeout_seconds,
            ).strip()
            data = pytesseract.image_to_data(
                image,
                lang=languages,
                output_type=pytesseract.Output.DICT,
                timeout=settings.ocr_page_timeout_seconds,
            )
            confidence = _mean_confidence(data)
        except pytesseract.TesseractError:
            try:
                text = pytesseract.image_to_string(
                    image,
                    lang="eng",
                    timeout=settings.ocr_page_timeout_seconds,
                ).strip()
                data = pytesseract.image_to_data(
                    image,
                    lang="eng",
                    output_type=pytesseract.Output.DICT,
                    timeout=settings.ocr_page_timeout_seconds,
                )
                confidence = _mean_confidence(data)
            except Exception as exc:
                text = f"OCR failed for page {index} of {path.name}. Human review required. Reason: {exc}"
                confidence = 0.0
        except Exception as exc:
            text = f"OCR failed for page {index} of {path.name}. Human review required. Reason: {exc}"
            confidence = 0.0
        pages.append(ParsedPage(page_number=index, text=text, ocr_confidence=confidence))

    return ParsedDocument(pages=pages or ocr_stub(path).pages)
