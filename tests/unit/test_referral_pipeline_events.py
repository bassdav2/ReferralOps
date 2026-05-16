from __future__ import annotations

from backend.app.db.models import ReferralPipelineEvent
from backend.app.referral.pipeline_events import record_pipeline_event


def test_record_pipeline_event_persists_small_payload(session):
    event = record_pipeline_event(
        session,
        stage="ocr",
        status="ok",
        message="OCR confidence 0.92",
        document_id="doc-1",
        payload={"ocr_min_confidence": 0.92},
    )
    session.commit()

    stored = session.get(ReferralPipelineEvent, event.id)

    assert stored is not None
    assert stored.document_id == "doc-1"
    assert stored.stage == "ocr"
    assert stored.status == "ok"
    assert stored.payload_json == {"ocr_min_confidence": 0.92}


def test_record_pipeline_event_does_not_commit_by_default(session, monkeypatch):
    committed = False

    def fake_commit():
        nonlocal committed
        committed = True

    monkeypatch.setattr(session, "commit", fake_commit)

    record_pipeline_event(session, stage="model", status="started", message="Gemma analysis started")

    assert committed is False
