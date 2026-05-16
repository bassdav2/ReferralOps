from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from backend.app.documents.parser_pdf import ParsedPage

OcrStatus = Literal["ok", "low", "failed", "unknown"]


class OcrQuality(BaseModel):
    min_confidence: float | None
    status: OcrStatus
    warnings: list[str]
    human_review_required: bool


def _looks_like_ocr_failure(page: ParsedPage) -> bool:
    text = page.text.strip().lower()
    if not text:
        return page.ocr_confidence is not None
    return text.startswith("ocr failed") or text.startswith("ocr is not available")


def evaluate_ocr_quality(pages: list[ParsedPage], threshold: float) -> OcrQuality:
    confidences = [page.ocr_confidence for page in pages if page.ocr_confidence is not None]
    if not confidences:
        return OcrQuality(
            min_confidence=None,
            status="unknown",
            warnings=[],
            human_review_required=False,
        )

    min_confidence = min(confidences)
    if min_confidence <= 0.0 or any(_looks_like_ocr_failure(page) for page in pages):
        return OcrQuality(
            min_confidence=min_confidence,
            status="failed",
            warnings=["OCR failed or produced no readable text. Human review required."],
            human_review_required=True,
        )
    if min_confidence < threshold:
        return OcrQuality(
            min_confidence=min_confidence,
            status="low",
            warnings=[
                f"Low OCR confidence ({min_confidence:.2f}) is below the configured threshold ({threshold:.2f})."
            ],
            human_review_required=True,
        )
    return OcrQuality(
        min_confidence=min_confidence,
        status="ok",
        warnings=[],
        human_review_required=False,
    )
