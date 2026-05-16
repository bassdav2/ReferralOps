from __future__ import annotations

from pathlib import Path

from backend.app.db.models import Document, ReferralCase, ReferralPipelineEvent
from backend.app.referral.demo_preload import DEMO_PRELOAD_MODEL_PROFILE, preload_referral_demo_state


def test_preload_referral_demo_state_creates_two_analyzed_cases(
    monkeypatch, session, tmp_path: Path, reset_runtime_caches
):
    monkeypatch.setenv("DEMO_PRELOAD_REFERRALS", "true")
    monkeypatch.setenv("REFERRAL_INBOX_BACKEND", "filesystem")
    monkeypatch.setenv("REFERRAL_INBOX_DIR", str(tmp_path / "referral_inbox"))
    monkeypatch.setenv("DEMO_PRELOAD_REFERRALS_DIR", str(Path("demos/referral_inbox_samples").resolve()))
    reset_runtime_caches()

    created = preload_referral_demo_state(session)

    documents = session.query(Document).order_by(Document.title.asc()).all()
    cases = session.query(ReferralCase).order_by(ReferralCase.created_at.asc()).all()
    model_events = (
        session.query(ReferralPipelineEvent)
        .filter(ReferralPipelineEvent.stage == "model", ReferralPipelineEvent.status == "ok")
        .all()
    )
    assert created == 2
    assert len(documents) == 2
    assert len(cases) == 2
    assert {case.model_profile for case in cases} == {DEMO_PRELOAD_MODEL_PROFILE}
    assert {event.payload_json["model_profile"] for event in model_events} == {DEMO_PRELOAD_MODEL_PROFILE}
    assert all("Preloaded demo analysis" in event.message for event in model_events)
    assert sorted(path.name for path in (tmp_path / "referral_inbox").glob("*.pdf")) == [
        "001_kardiologie_complete_referral.pdf",
        "002_innere_medizin_missing_phone_scan.pdf",
    ]


def test_preload_referral_demo_state_is_idempotent(monkeypatch, session, tmp_path: Path, reset_runtime_caches):
    monkeypatch.setenv("DEMO_PRELOAD_REFERRALS", "true")
    monkeypatch.setenv("REFERRAL_INBOX_BACKEND", "filesystem")
    monkeypatch.setenv("REFERRAL_INBOX_DIR", str(tmp_path / "referral_inbox"))
    monkeypatch.setenv("DEMO_PRELOAD_REFERRALS_DIR", str(Path("demos/referral_inbox_samples").resolve()))
    reset_runtime_caches()

    assert preload_referral_demo_state(session) == 2
    assert preload_referral_demo_state(session) == 0
    assert session.query(ReferralCase).count() == 2
