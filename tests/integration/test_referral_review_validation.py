from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.db.models import ReferralCase
from backend.app.documents.registry import register_file
from backend.app.main import app
from backend.app.referral.service import analyze_referral
from backend.app.security.auth import get_current_user


def _case_for_review(session, tmp_path: Path):
    sample = tmp_path / "review_validation.txt"
    sample.write_text("Zuweisung wegen Thoraxbeschwerden und Dyspnoe.", encoding="utf-8")
    user = get_current_user("sekretariat_kardiologie")
    document = register_file(
        session,
        sample,
        title="review validation",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
    )
    return analyze_referral(session, document.id, user)


def test_correct_review_requires_corrected_analysis(session, tmp_path: Path):
    case = _case_for_review(session, tmp_path)

    response = TestClient(app).post(
        f"/api/referrals/{case.id}/review",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
        json={"decision": "correct", "corrected_analysis": None},
    )

    assert response.status_code == 422


def test_confirm_review_rejects_corrected_analysis(session, tmp_path: Path):
    case = _case_for_review(session, tmp_path)

    response = TestClient(app).post(
        f"/api/referrals/{case.id}/review",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
        json={
            "decision": "confirm",
            "corrected_analysis": case.analysis.model_dump(mode="json"),
        },
    )

    assert response.status_code == 422


def test_correct_review_accepts_corrected_analysis(session, tmp_path: Path):
    case = _case_for_review(session, tmp_path)
    corrected = case.analysis.model_dump(mode="json")
    corrected["patient"]["insurance_id"] = "SYNTH-ROUND8"

    response = TestClient(app).post(
        f"/api/referrals/{case.id}/review",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
        json={"decision": "correct", "corrected_analysis": corrected},
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "correct"


def test_corrected_analysis_cannot_set_unknown_routing_target(session, tmp_path: Path):
    case = _case_for_review(session, tmp_path)
    corrected = case.analysis.model_dump(mode="json")
    corrected["routing_proposal"]["routing_target"] = "neuro_magic"
    corrected["routing_proposal"]["department"] = "Neuro Magic"
    corrected["routing_proposal"]["confidence"] = 0.91

    response = TestClient(app).post(
        f"/api/referrals/{case.id}/review",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
        json={"decision": "correct", "corrected_analysis": corrected},
    )

    stored_case = session.get(ReferralCase, case.id)

    assert response.status_code == 200
    assert stored_case is not None
    assert stored_case.analysis_json["routing_proposal"]["routing_target"] is None
    assert stored_case.analysis_json["routing_proposal"]["confidence"] == 0.3
    assert any("not in taxonomy" in warning for warning in stored_case.analysis_json["warnings"])


def test_corrected_analysis_document_id_must_match_case(session, tmp_path: Path):
    case = _case_for_review(session, tmp_path)
    corrected = case.analysis.model_dump(mode="json")
    corrected["document_id"] = "different-document"

    response = TestClient(app).post(
        f"/api/referrals/{case.id}/review",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
        json={"decision": "correct", "corrected_analysis": corrected},
    )

    assert response.status_code == 400
