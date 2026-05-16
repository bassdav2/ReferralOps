from __future__ import annotations

from backend.app.core.config import get_settings
from backend.app.documents.parser_pdf import ParsedPage
from backend.app.referral.ocr_quality import evaluate_ocr_quality


def test_ocr_min_confidence_setting_defaults_to_075(reset_runtime_caches):
    reset_runtime_caches()

    assert get_settings().ocr_min_confidence == 0.75


def test_ocr_min_confidence_setting_can_be_overridden(monkeypatch, reset_runtime_caches):
    monkeypatch.setenv("OCR_MIN_CONFIDENCE", "0.61")
    reset_runtime_caches()

    assert get_settings().ocr_min_confidence == 0.61


def test_low_ocr_quality_returns_review_warning():
    quality = evaluate_ocr_quality(
        [ParsedPage(page_number=1, text="Zuweisung wegen Thoraxbeschwerden.", ocr_confidence=0.62)],
        threshold=0.75,
    )

    assert quality.status == "low"
    assert quality.min_confidence == 0.62
    assert quality.human_review_required is True
    assert "Low OCR confidence" in " ".join(quality.warnings)


def test_unknown_ocr_quality_has_no_warning():
    quality = evaluate_ocr_quality(
        [ParsedPage(page_number=1, text="Searchable PDF text.", ocr_confidence=None)],
        threshold=0.75,
    )

    assert quality.status == "unknown"
    assert quality.min_confidence is None
    assert quality.human_review_required is False
    assert quality.warnings == []
