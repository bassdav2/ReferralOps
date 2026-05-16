from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from backend.app.db.models import Document
from backend.app.main import app
from backend.app.referral.pipeline_events import record_pipeline_event


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


def test_pipeline_events_endpoint_returns_recent_events_descending_or_chronological_consistently(session):
    document = _document(session, "event-doc")
    first = record_pipeline_event(
        session,
        stage="pypdf",
        status="started",
        message="PyPDF/Text extraction started",
        document_id=document.id,
    )
    second = record_pipeline_event(
        session,
        stage="pypdf",
        status="ok",
        message="PyPDF extracted 12 characters across 1 pages",
        document_id=document.id,
    )
    first.created_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    second.created_at = datetime(2026, 1, 1, 12, 1, tzinfo=UTC)
    session.commit()

    response = _client().get(
        "/api/referrals/pipeline-events?limit=10",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload[:2]] == [second.id, first.id]


def test_pipeline_events_endpoint_supports_document_filter(session):
    shown = _document(session, "shown-doc")
    hidden_by_filter = _document(session, "hidden-by-filter-doc")
    record_pipeline_event(session, stage="ocr", status="ok", message="shown", document_id=shown.id)
    record_pipeline_event(
        session,
        stage="ocr",
        status="ok",
        message="hidden",
        document_id=hidden_by_filter.id,
    )
    session.commit()

    response = _client().get(
        f"/api/referrals/pipeline-events?document_id={shown.id}",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
    )

    assert response.status_code == 200
    assert [item["message"] for item in response.json()] == ["shown"]
