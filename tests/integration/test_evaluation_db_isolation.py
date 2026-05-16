from __future__ import annotations

from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.db.models import Document, GuidelineChunk, GuidelineDocument, ReferralCase
from backend.app.documents.registry import register_file
from backend.app.evaluation.metrics_rag import evaluate_demo_guidelines
from backend.app.evaluation.metrics_referrals import evaluate_demo_referrals
from backend.app.referral.service import analyze_referral
from backend.app.security.auth import get_current_user


def test_referral_evaluation_does_not_drop_existing_app_db(monkeypatch, session, tmp_path: Path):
    sample = tmp_path / "app_referral.txt"
    sample.write_text("Zuweisung wegen Thoraxbeschwerden und Dyspnoe.", encoding="utf-8")
    user = get_current_user("sekretariat_kardiologie")
    document = register_file(
        session,
        sample,
        title="app db referral",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
    )
    case = analyze_referral(session, document.id, user)
    eval_db = Path("prototype_eval_referrals.db")
    eval_db.unlink(missing_ok=True)

    monkeypatch.setenv("DATABASE_URL", "sqlite:///./prototype_eval_referrals.db")
    get_settings.cache_clear()

    metrics = evaluate_demo_referrals()

    assert metrics["critical_errors"] == 0
    assert session.get(Document, document.id) is not None
    assert session.get(ReferralCase, case.id) is not None
    eval_db.unlink(missing_ok=True)


def test_guideline_evaluation_does_not_drop_existing_app_db(monkeypatch, session):
    document = GuidelineDocument(
        id="app-guideline-doc",
        source_system="test",
        external_id="test:guideline.md",
        title="App Guideline",
        owner_department="IT",
        version="demo-v1",
        status="active",
        access_groups=["it_users"],
        escalation_contact=None,
        source_uri="memory",
        checksum="app-guideline",
    )
    chunk = GuidelineChunk(
        id="app-guideline-chunk",
        document_id=document.id,
        heading_path=["App Guideline"],
        chunk_text="KIS-Zugang beantragen.",
        token_count=3,
        embedding=[0.0] * 48,
        page=None,
        order_index=0,
    )
    session.add_all([document, chunk])
    session.commit()
    eval_db = Path("prototype_eval_guidelines.db")
    eval_db.unlink(missing_ok=True)

    monkeypatch.setenv("DATABASE_URL", "sqlite:///./prototype_eval_guidelines.db")
    get_settings.cache_clear()

    metrics = evaluate_demo_guidelines()

    assert metrics["critical_errors"] == 0
    assert session.get(GuidelineDocument, document.id) is not None
    assert session.get(GuidelineChunk, chunk.id) is not None
    eval_db.unlink(missing_ok=True)
