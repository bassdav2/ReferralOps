from __future__ import annotations

from backend.app.db.models import AuditEvent
from backend.app.rag.answerer import answer_guideline_question
from backend.app.rag.ingest import ingest_guideline_sources
from backend.app.security.auth import get_current_user


def test_guideline_answer_has_source_and_audit(session):
    user = get_current_user("it_admin")
    result = ingest_guideline_sources(session)
    assert result["documents"] >= 4

    answer = answer_guideline_question(session, "Wie beantrage ich einen KIS-Zugang?", user)
    assert answer.confidence in {"high", "medium"}
    assert answer.sources
    assert "KIS" in answer.answer

    events = session.query(AuditEvent).all()
    assert any(event.action == "guideline.answer" for event in events)


def test_patient_specific_question_is_refused(session):
    user = get_current_user("hygiene_user")
    ingest_guideline_sources(session)
    answer = answer_guideline_question(session, "Soll Patient Max Muster heute entlassen werden?", user)
    assert answer.confidence == "no_answer"
    assert "patient_specific_or_clinical" in answer.safety_flags
    assert answer.sources == []
