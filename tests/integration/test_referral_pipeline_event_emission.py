from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.core.runtime_model_config import LocalModelConfig, write_local_model_config
from backend.app.db.models import Document, DocumentPage, ReferralPipelineEvent
from backend.app.documents.registry import register_file
from backend.app.model_gateway.test_double_client import TestDoubleLLMClient
from backend.app.referral.review import review_referral_case
from backend.app.referral.schemas import ReviewRequest
from backend.app.referral.service import analyze_referral
from backend.app.security.auth import get_current_user


@pytest.fixture
def demo_output_dir(tmp_path: Path, monkeypatch, reset_runtime_caches):
    output_dir = tmp_path / "demo_outputs" / "referrals"
    monkeypatch.setenv("REFERRAL_DEMO_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("DEMO_OUTPUTS_ENABLED", "true")
    reset_runtime_caches()
    yield output_dir
    reset_runtime_caches()


def _events(session, document_id: str) -> list[ReferralPipelineEvent]:
    return (
        session.query(ReferralPipelineEvent)
        .filter(ReferralPipelineEvent.document_id == document_id)
        .order_by(ReferralPipelineEvent.created_at.asc())
        .all()
    )


def _text_document(session, tmp_path: Path, name: str = "referral.txt") -> Document:
    sample = tmp_path / name
    sample.write_text(
        "Zuweisung wegen Thoraxbeschwerden und Dyspnoe. Patient: Lea Beispiel. "
        "Telefon: +41 44 000 00 00. Zuweisende Aerztin: Dr. Demo.",
        encoding="utf-8",
    )
    return register_file(
        session,
        sample,
        title=name,
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
    )


def test_analyze_referral_emits_pypdf_ocr_model_validation_worklist_events(session, tmp_path: Path):
    user = get_current_user("sekretariat_kardiologie")
    document = _text_document(session, tmp_path)

    case = analyze_referral(session, document.id, user)

    by_stage = {event.stage: event for event in _events(session, document.id)}
    assert case.id
    assert by_stage["pypdf"].message.startswith("PyPDF")
    assert by_stage["ocr"].status == "ok"
    assert by_stage["model"].status == "ok"
    assert by_stage["validation"].stage == "validation"
    assert by_stage["worklist"].case_id == case.id


def test_low_ocr_analysis_emits_warning_event(session):
    user = get_current_user("sekretariat_kardiologie")
    document = Document(
        id="low-ocr-doc",
        source_system="test_referrals",
        external_id="missing-low-ocr.pdf",
        title="low ocr",
        mime_type="application/pdf",
        sha256="a" * 64,
        storage_pointer="missing-low-ocr.pdf",
        source_uri="missing-low-ocr.pdf",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
        parse_status="parsed",
    )
    session.add(document)
    session.add(
        DocumentPage(
            document_id=document.id,
            page_number=1,
            text="Zuweisung wegen Thoraxbeschwerden und Dyspnoe.",
            ocr_confidence=0.61,
        )
    )
    session.commit()

    analyze_referral(session, document.id, user)

    ocr_event = next(event for event in _events(session, document.id) if event.stage == "ocr")
    assert ocr_event.status == "warning"
    assert ocr_event.payload_json["ocr_status"] == "low"


def test_model_failure_emits_failed_model_event_and_safe_review_case(monkeypatch, session, tmp_path: Path):
    class RaisingClient:
        def generate_json(self, **kwargs):
            raise RuntimeError("local model unavailable")

    monkeypatch.setattr("backend.app.referral.service.get_llm_client", lambda: RaisingClient())
    user = get_current_user("sekretariat_kardiologie")
    document = _text_document(session, tmp_path, "model_failure.txt")

    case = analyze_referral(session, document.id, user)

    model_event = next(
        event for event in _events(session, document.id) if event.stage == "model" and event.status == "failed"
    )
    assert model_event.message == "Model analysis failed, safe review case created"
    assert model_event.payload_json["error_type"] == "RuntimeError"
    assert case.analysis.human_review_required is True
    assert any("model gateway failed" in warning.lower() for warning in case.analysis.warnings)


def test_analyze_referral_records_runtime_model_profile(monkeypatch, session, tmp_path: Path, reset_runtime_caches):
    write_local_model_config(
        LocalModelConfig(
            base_url="http://localhost:1234/v1",
            model_id="google/gemma-4-31B-it",
            timeout_seconds=1,
        )
    )
    reset_runtime_caches()
    monkeypatch.setattr("backend.app.referral.service.get_llm_client", lambda: TestDoubleLLMClient())
    user = get_current_user("sekretariat_kardiologie")
    document = _text_document(session, tmp_path, "runtime_model_profile.txt")

    case = analyze_referral(session, document.id, user)

    model_event = next(
        event for event in _events(session, document.id) if event.stage == "model" and event.status == "ok"
    )
    assert case.model_profile == "google/gemma-4-31B-it"
    assert model_event.message.startswith("Model proposed")
    assert model_event.payload_json["model_profile"] == "google/gemma-4-31B-it"


def test_review_emits_review_event(session, tmp_path: Path, demo_output_dir: Path):
    user = get_current_user("sekretariat_kardiologie")
    document = _text_document(session, tmp_path, "review_event.txt")
    case = analyze_referral(session, document.id, user)

    review_referral_case(session, case.id, user, ReviewRequest(decision="confirm"))

    review_event = next(event for event in _events(session, document.id) if event.stage == "review")
    assert review_event.status == "completed"
    assert review_event.payload_json == {"decision": "confirm", "reviewer": user.id}
