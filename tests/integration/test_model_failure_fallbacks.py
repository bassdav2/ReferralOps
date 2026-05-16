from __future__ import annotations

from pathlib import Path

from backend.app.db.models import AuditEvent
from backend.app.documents.registry import register_file
from backend.app.rag.answerer import answer_guideline_question
from backend.app.rag.ingest import ingest_guideline_sources
from backend.app.referral.service import analyze_referral
from backend.app.security.auth import get_current_user


class RaisingClient:
    def generate_json(self, **kwargs):
        raise RuntimeError("local endpoint unavailable")


def test_referral_model_gateway_failure_creates_human_review_case(monkeypatch, session, tmp_path: Path):
    sample = tmp_path / "referral.txt"
    sample.write_text("Zuweisung wegen Thoraxbeschwerden und Dyspnoe.", encoding="utf-8")
    user = get_current_user("sekretariat_kardiologie")
    document = register_file(
        session,
        sample,
        title="fallback referral",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
    )
    monkeypatch.setattr("backend.app.referral.service.get_llm_client", lambda: RaisingClient())

    case = analyze_referral(session, document.id, user)
    events = session.query(AuditEvent).filter(AuditEvent.object_id == case.id).all()

    assert case.analysis.human_review_required is True
    assert "Local model gateway failed or returned invalid JSON. Human review required." in case.analysis.warnings
    assert any(event.action == "referral.model_suggestion" for event in events)
    assert all("local endpoint unavailable" not in str(event.payload_json) for event in events)


def test_guideline_model_gateway_failure_returns_cited_extractive_fallback(monkeypatch, reset_runtime_caches, session):
    ingest_guideline_sources(session)
    user = get_current_user("it_admin")
    monkeypatch.setenv("MODEL_PROVIDER", "gemma_vllm")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://localhost:1234/v1")
    reset_runtime_caches()
    monkeypatch.setattr("backend.app.rag.answerer.get_llm_client", lambda: RaisingClient())

    answer = answer_guideline_question(session, "Wie beantrage ich einen KIS-Zugang?", user)
    event = session.query(AuditEvent).filter(AuditEvent.action == "guideline.answer").one()

    assert answer.confidence == "medium"
    assert answer.sources
    assert "It Access" in answer.sources[0].title
    assert "Ein KIS-Zugang wird im IT-Serviceportal beantragt" in answer.answer
    assert "extractive_fallback" in answer.safety_flags
    assert "model_gateway_error" in answer.safety_flags
    assert event.input_hash is not None
    assert "local endpoint unavailable" not in str(event.payload_json)
