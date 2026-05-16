from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import get_settings
from backend.app.db.models import AuditEvent
from backend.app.documents.registry import register_file
from backend.app.main import app
from backend.app.referral.service import analyze_referral
from backend.app.security.auth import get_current_user


def test_long_guideline_question_is_rejected(monkeypatch):
    monkeypatch.setenv("MAX_GUIDELINE_QUESTION_CHARS", "20")
    get_settings.cache_clear()

    response = TestClient(app).post(
        "/api/guidelines/chat",
        headers={"X-Demo-User": "it_admin"},
        json={"question": "x" * 21},
    )

    assert response.status_code == 400


def test_long_referral_text_is_truncated_with_warning(monkeypatch, session, tmp_path: Path):
    monkeypatch.setenv("MAX_REFERRAL_TEXT_CHARS", "80")
    get_settings.cache_clear()
    sample = tmp_path / "long_referral.txt"
    sample.write_text("Zuweisung wegen Thoraxbeschwerden und Dyspnoe. " + ("x" * 1000), encoding="utf-8")
    user = get_current_user("sekretariat_kardiologie")
    document = register_file(
        session,
        sample,
        title="long referral",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
    )

    case = analyze_referral(session, document.id, user)
    event = (
        session.query(AuditEvent)
        .filter(AuditEvent.action == "referral.model_suggestion", AuditEvent.object_id == case.id)
        .one()
    )

    assert any(
        warning.startswith("Document text was truncated for demo model context")
        for warning in case.analysis.warnings
    )
    assert event.input_hash is not None
    assert len(event.input_hash) == 64
    assert event.payload_json == {"document_id": document.id}
