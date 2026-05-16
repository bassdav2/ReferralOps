from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.app.core.config import get_settings
from backend.app.db.models import AuditEvent, ReferralCase
from backend.app.documents.registry import register_file
from backend.app.referral.review import review_referral_case
from backend.app.referral.schemas import ReviewRequest
from backend.app.referral.service import analyze_referral
from backend.app.referral.writeback import writeback_case
from backend.app.security.auth import get_current_user


def _reviewed_case(session, tmp_path: Path, decision: str = "confirm"):
    sample = tmp_path / f"writeback_{decision}.txt"
    sample.write_text("Zuweisung wegen Thoraxbeschwerden und Dyspnoe.", encoding="utf-8")
    user = get_current_user("sekretariat_kardiologie")
    document = register_file(
        session,
        sample,
        title=f"writeback {decision}",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
    )
    case = analyze_referral(session, document.id, user)
    review_referral_case(session, case.id, user, ReviewRequest(decision=decision))
    return case, user


def test_writeback_disabled_logs_audit_events(session, tmp_path: Path):
    case, user = _reviewed_case(session, tmp_path, "confirm")

    result = writeback_case(session, case.id, user)
    actions = {
        event.action
        for event in session.query(AuditEvent).filter(AuditEvent.object_id == case.id).all()
    }

    assert result["status"] == "demo_written"
    assert result["path"].startswith("writeback/")
    assert "referral.writeback.attempt" in actions
    assert "referral.writeback.disabled" in actions


def test_writeback_disabled_by_default_writes_local_demo_json(session, tmp_path: Path):
    case, user = _reviewed_case(session, tmp_path, "confirm")

    result = writeback_case(session, case.id, user)
    stored = session.get(ReferralCase, case.id)

    assert result["status"] == "demo_written"
    assert "local JSON" in result["message"]
    assert result["path"].startswith("writeback/")
    assert result["extra_paths"]
    assert result["extra_paths"][0].startswith("departments/")
    assert (tmp_path / "demo_outputs" / "referrals" / result["extra_paths"][0]).exists()
    assert stored.status == "writeback_sent"


def test_writeback_is_idempotent_after_first_success(session, tmp_path: Path):
    case, user = _reviewed_case(session, tmp_path, "confirm")

    first = writeback_case(session, case.id, user)
    output_dir = get_settings().referral_demo_output_dir
    json_count = len(list(output_dir.rglob("*.json")))
    second = writeback_case(session, case.id, user)

    assert second["status"] == first["status"]
    assert second["path"] == first["path"]
    assert second["extra_paths"] == first["extra_paths"]
    assert len(list(output_dir.rglob("*.json"))) == json_count


def test_review_cannot_change_after_writeback_sent(session, tmp_path: Path):
    case, user = _reviewed_case(session, tmp_path, "confirm")
    writeback_case(session, case.id, user)

    with pytest.raises(HTTPException):
        review_referral_case(session, case.id, user, ReviewRequest(decision="reject"))


def test_writeback_enabled_requires_confirm_or_correct(monkeypatch, session, tmp_path: Path):
    monkeypatch.setenv("WRITEBACK_ENABLED", "true")
    get_settings.cache_clear()
    case, user = _reviewed_case(session, tmp_path, "confirm")

    result = writeback_case(session, case.id, user)

    assert result["status"] == "local_json_written"
    assert result["case_id"] == case.id
    assert result["path"].startswith("writeback/")


@pytest.mark.parametrize("decision", ["reject", "question"])
def test_writeback_rejects_non_confirmed_review_statuses(session, tmp_path: Path, decision: str):
    case, user = _reviewed_case(session, tmp_path, decision)

    with pytest.raises(HTTPException):
        writeback_case(session, case.id, user)
