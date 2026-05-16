from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.documents.registry import register_file
from backend.app.main import app
from backend.app.referral.service import analyze_referral
from backend.app.security.auth import get_current_user


@pytest.fixture
def demo_output_dir(tmp_path: Path, monkeypatch, reset_runtime_caches):
    output_dir = tmp_path / "demo_outputs" / "referrals"
    monkeypatch.setenv("REFERRAL_DEMO_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("DEMO_OUTPUTS_ENABLED", "true")
    reset_runtime_caches()
    yield output_dir
    reset_runtime_caches()


def _client() -> TestClient:
    return TestClient(app)


def _case_for_review(session, tmp_path: Path, name: str):
    sample = tmp_path / f"{name}.txt"
    sample.write_text(
        "Zuweisung wegen Thoraxbeschwerden und Dyspnoe. Patient: Demo Fall, geboren 01.01.1980. "
        "Telefon: +41 44 000 00 00. Zuweisende Aerztin: Dr. Petra Demo.",
        encoding="utf-8",
    )
    document = register_file(
        session,
        sample,
        title=f"{name}.txt",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
    )
    return analyze_referral(session, document.id, get_current_user("sekretariat_kardiologie"))


def _review(case_id: str, decision: str, corrected_analysis: dict | None = None):
    return _client().post(
        f"/api/referrals/{case_id}/review",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
        json={
            "decision": decision,
            "corrected_analysis": corrected_analysis,
            "comment": "Demo review comment",
        },
    )


def _payloads(output_dir: Path, folder: str) -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted((output_dir / folder).glob("*.json"))]


def test_confirm_review_writes_confirmed_output_json(session, tmp_path: Path, demo_output_dir: Path):
    case = _case_for_review(session, tmp_path, "confirm-output")

    response = _review(case.id, "confirm")

    assert response.status_code == 200
    payloads = _payloads(demo_output_dir, "confirmed")
    assert payloads[0]["case_id"] == case.id
    assert payloads[0]["decision"] == "confirm"


def test_correct_review_writes_corrected_output_json(session, tmp_path: Path, demo_output_dir: Path):
    case = _case_for_review(session, tmp_path, "correct-output")
    corrected = case.analysis.model_dump(mode="json")
    corrected["patient"]["insurance_id"] = "SYN-CORRECTED"

    response = _review(case.id, "correct", corrected)

    assert response.status_code == 200
    payloads = _payloads(demo_output_dir, "corrected")
    assert payloads[0]["case_id"] == case.id
    assert payloads[0]["decision"] == "correct"


def test_question_review_writes_questions_output_json(session, tmp_path: Path, demo_output_dir: Path):
    case = _case_for_review(session, tmp_path, "question-output")

    response = _review(case.id, "question")

    assert response.status_code == 200
    payloads = _payloads(demo_output_dir, "questions")
    assert payloads[0]["case_id"] == case.id
    assert payloads[0]["decision"] == "question"


def test_reject_review_writes_rejected_output_json(session, tmp_path: Path, demo_output_dir: Path):
    case = _case_for_review(session, tmp_path, "reject-output")

    response = _review(case.id, "reject")

    assert response.status_code == 200
    payloads = _payloads(demo_output_dir, "rejected")
    assert payloads[0]["case_id"] == case.id
    assert payloads[0]["decision"] == "reject"


def test_demo_outputs_endpoint_lists_recent_outputs(session, tmp_path: Path, demo_output_dir: Path):
    first = _case_for_review(session, tmp_path, "output-list-first")
    second = _case_for_review(session, tmp_path, "output-list-second")
    assert _review(first.id, "confirm").status_code == 200
    assert _review(second.id, "reject").status_code == 200

    response = _client().get(
        "/api/referrals/demo-outputs?limit=20",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) >= 2
    assert {item["case_id"] for item in payload} >= {first.id, second.id}
    assert all(item["relative_path"].endswith(".json") for item in payload)


def test_restricted_user_cannot_list_demo_outputs(session, tmp_path: Path, demo_output_dir: Path):
    case = _case_for_review(session, tmp_path, "restricted-output")
    assert _review(case.id, "confirm").status_code == 200

    response = _client().get("/api/referrals/demo-outputs", headers={"X-Demo-User": "restricted_user"})

    assert response.status_code == 403


def test_correct_review_with_edited_fields_writes_corrected_output_json(session, tmp_path: Path, demo_output_dir: Path):
    case = _case_for_review(session, tmp_path, "correct-edited-output")
    corrected = case.analysis.model_dump(mode="json")
    corrected["patient"]["name"] = "Demo Korrigiert"
    corrected["patient"]["phone"] = "+41 44 123 45 67"
    corrected["patient"]["insurance_id"] = "SYN-EDITED"
    corrected["referring_party"]["physician_name"] = "Dr. Korrigiert"
    corrected["referring_party"]["organization"] = "Praxis Korrigiert"
    corrected["clinical_context_for_admin_routing"]["reason_for_referral"] = "Korrigierter Demo-Grund"
    corrected["routing_proposal"]["routing_target"] = "kardiologie"
    corrected["routing_proposal"]["department"] = "Kardiologie"

    response = _review(case.id, "correct", corrected)

    assert response.status_code == 200
    payloads = _payloads(demo_output_dir, "corrected")
    assert payloads[0]["case_id"] == case.id
    assert payloads[0]["decision"] == "correct"
    assert payloads[0]["routing_target"] == "kardiologie"
