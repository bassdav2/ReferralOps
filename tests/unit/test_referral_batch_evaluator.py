from __future__ import annotations

from pathlib import Path

from backend.app.referral.schemas import ReferralAnalysis
from scripts.evaluate_referral_batch import (
    _analysis_from_fixture,
    _metrics,
    _resolve_pdf_path,
    _run_live_predictions,
    _sample_rows,
)


def test_stratified_sampling_is_deterministic():
    rows = [
        {"case_id": "a1", "routing_target": "kardiologie"},
        {"case_id": "a2", "routing_target": "kardiologie"},
        {"case_id": "b1", "routing_target": "radiologie"},
        {"case_id": "b2", "routing_target": "radiologie"},
        {"case_id": "c1", "routing_target": None},
    ]

    first = _sample_rows(rows, limit=3, seed=7, strategy="stratified")
    second = _sample_rows(rows, limit=3, seed=7, strategy="stratified")

    assert first == second
    assert {row["routing_target"] for row in first} == {"kardiologie", "radiologie", None}


def test_fake_fixture_metrics_include_invalid_and_null_routes():
    rows = [
        {"case_id": "valid", "file_name": "valid.pdf", "routing_target": "radiologie", "human_review_required": False},
        {
            "case_id": "invalid",
            "file_name": "invalid.pdf",
            "routing_target": "kardiologie",
            "human_review_required": True,
        },
    ]
    predictions = {
        "valid.pdf": _analysis_from_fixture(rows[0], "valid"),
        "invalid.pdf": _analysis_from_fixture(rows[1], "truncated"),
    }
    predictions["valid.pdf"].ocr_status = "ok"
    predictions["invalid.pdf"].ocr_status = "low"

    metrics = _metrics(rows, predictions, dataset="unit")

    assert metrics["cases"] == 2
    assert metrics["model_response_invalid_count"] == 1
    assert metrics["null_unknown_route_rate"] == 0.5
    assert metrics["routing_top1_exact_accuracy"] == 0.5
    assert metrics["invalid_response_rows"]
    assert {row["slice"] for row in metrics["ocr_slice_metrics"]} == {"low", "ok"}


def test_resolve_pdf_path_uses_pdf_dir(tmp_path: Path):
    labels = tmp_path / "metadata.csv"
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    pdf = pdf_dir / "case.pdf"
    pdf.write_text("synthetic referral", encoding="utf-8")

    resolved = _resolve_pdf_path({"file_name": "case.pdf"}, labels_path=labels, pdf_dir=pdf_dir)

    assert resolved == pdf


def test_live_predictions_can_run_with_monkeypatched_model(monkeypatch, tmp_path: Path):
    labels = tmp_path / "metadata.csv"
    pdf = tmp_path / "case.txt"
    pdf.write_text("Zuweisung wegen CT.", encoding="utf-8")
    row = {"case_id": "case", "file_name": "case.txt", "path": str(pdf), "routing_target": "radiologie"}

    class FakeCase:
        analysis = ReferralAnalysis(
            document_id="doc",
            routing_proposal={"routing_target": "radiologie", "confidence": 0.9},
            human_review_required=False,
        )

    monkeypatch.setattr("scripts.evaluate_referral_batch.analyze_referral", lambda *args, **kwargs: FakeCase())

    predictions = _run_live_predictions([row], labels_path=labels, pdf_dir=None, user_id="sekretariat_kardiologie")

    assert predictions["case.txt"].routing_proposal.routing_target == "radiologie"
