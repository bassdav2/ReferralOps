from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.documents.registry import register_file
from backend.app.main import app
from backend.app.referral.service import analyze_referral
from backend.app.security.auth import get_current_user


def test_missing_x_demo_user_cannot_list_documents():
    response = TestClient(app).get("/api/documents")

    assert response.status_code in {401, 403}


def test_missing_x_demo_user_cannot_access_referral_case(session, tmp_path: Path):
    user = get_current_user("sekretariat_kardiologie")
    sample = tmp_path / "auth_referral.txt"
    sample.write_text("Zuweisung wegen Thoraxbeschwerden und Dyspnoe.", encoding="utf-8")
    document = register_file(
        session,
        sample,
        title="auth referral",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
    )
    case = analyze_referral(session, document.id, user)

    response = TestClient(app).get(f"/api/referrals/{case.id}")

    assert response.status_code in {401, 403}


def test_unknown_x_demo_user_fails_closed():
    response = TestClient(app).get("/api/documents", headers={"X-Demo-User": "unknown-user"})

    assert response.status_code in {401, 403}
