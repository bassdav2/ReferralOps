from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.db.models import Document, DocumentPage
from backend.app.documents.registry import register_file
from backend.app.main import app
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


def _client() -> TestClient:
    return TestClient(app)


def _document(session, document_id: str) -> Document:
    document = Document(
        id=document_id,
        source_system="test_referrals",
        external_id=f"{document_id}.txt",
        title=f"{document_id}.txt",
        mime_type="text/plain",
        sha256=document_id[:1] * 64,
        storage_pointer=f"missing/{document_id}.txt",
        source_uri=f"missing/{document_id}.txt",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
        parse_status="pending",
    )
    session.add(document)
    session.commit()
    return document


def _text_document(session, tmp_path: Path, name: str):
    sample = tmp_path / name
    sample.write_text(
        "Zuweisung wegen Thoraxbeschwerden und Dyspnoe. Patient: Demo Fall. "
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


def _worklist_item(document_id: str) -> dict:
    response = _client().get("/api/referrals/cases", headers={"X-Demo-User": "sekretariat_kardiologie"})
    assert response.status_code == 200
    return next(item for item in response.json() if item["document_id"] == document_id)


def test_new_document_has_pending_pipeline_stages(session):
    document = _document(session, "new-pipeline-doc")

    item = _worklist_item(document.id)

    assert item["pipeline"]["inbox"]["status"] == "ok"
    assert item["pipeline"]["pypdf"]["status"] == "pending"
    assert item["pipeline"]["ocr"]["status"] == "pending"
    assert item["pipeline"]["model"]["status"] == "pending"
    assert item["pipeline"]["review"]["status"] == "pending"
    assert item["pipeline"]["output"]["status"] == "pending"


def test_analyzed_document_has_pypdf_ocr_model_worklist_stages(session, tmp_path: Path):
    user = get_current_user("sekretariat_kardiologie")
    document = _text_document(session, tmp_path, "analyzed-pipeline.txt")

    analyze_referral(session, document.id, user)

    item = _worklist_item(document.id)
    assert item["pipeline"]["pypdf"]["status"] == "ok"
    assert item["pipeline"]["ocr"]["status"] == "unknown"
    assert item["pipeline"]["model"]["status"] in {"ok", "warning"}
    assert item["pipeline"]["review"]["detail"] == "offen"


def test_low_ocr_document_pipeline_marks_ocr_warning(session):
    user = get_current_user("sekretariat_kardiologie")
    document = _document(session, "low-ocr-pipeline-doc")
    document.mime_type = "application/pdf"
    document.parse_status = "parsed"
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

    item = _worklist_item(document.id)
    assert item["pipeline"]["ocr"]["status"] == "warning"
    assert item["pipeline"]["ocr"]["label"] == "OCR 61%"


def test_reviewed_document_pipeline_marks_review_completed(session, tmp_path: Path, demo_output_dir: Path):
    user = get_current_user("sekretariat_kardiologie")
    document = _text_document(session, tmp_path, "reviewed-pipeline.txt")
    case = analyze_referral(session, document.id, user)

    review_referral_case(session, case.id, user, ReviewRequest(decision="confirm"))

    item = _worklist_item(document.id)
    assert item["pipeline"]["review"]["status"] == "completed"


def test_output_written_marks_output_completed(session, tmp_path: Path, demo_output_dir: Path):
    user = get_current_user("sekretariat_kardiologie")
    document = _text_document(session, tmp_path, "output-pipeline.txt")
    case = analyze_referral(session, document.id, user)

    review_referral_case(session, case.id, user, ReviewRequest(decision="confirm"))

    item = _worklist_item(document.id)
    assert item["pipeline"]["output"]["status"] == "completed"
    assert item["pipeline"]["output"]["detail"] == "JSON geschrieben"
