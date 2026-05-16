from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.db.models import Document, ReferralCase
from backend.app.documents.registry import register_file
from backend.app.main import app
from backend.app.referral.schemas import ReferralAnalysis
from backend.app.referral.service import analyze_referral
from backend.app.security.auth import get_current_user


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_restricted_user_cannot_access_referral_case(session, tmp_path: Path):
    sample = tmp_path / "private_referral.txt"
    sample.write_text("Zuweisung wegen Thoraxbeschwerden und Dyspnoe.", encoding="utf-8")

    owner = get_current_user("sekretariat_kardiologie")
    restricted = get_current_user("restricted_user")

    document = register_file(
        session,
        sample,
        title="private referral",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
    )
    case = analyze_referral(session, document.id, owner)

    from backend.app.referral.review import review_referral_case
    from backend.app.referral.schemas import ReviewRequest
    from backend.app.referral.service import get_referral_case
    from backend.app.referral.writeback import writeback_case

    with pytest.raises(HTTPException):
        get_referral_case(session, case.id, restricted)

    with pytest.raises(HTTPException):
        review_referral_case(session, case.id, restricted, ReviewRequest(decision="confirm"))

    with pytest.raises(HTTPException):
        writeback_case(session, case.id, restricted)


def test_referral_case_read_requires_reviewer_even_if_document_acl_is_broad(session):
    restricted = get_current_user("restricted_user")
    reviewer = get_current_user("sekretariat_kardiologie")
    document = Document(
        id="misconfigured-document",
        source_system="manual",
        external_id="misconfigured",
        title="misconfigured referral",
        mime_type="text/plain",
        sha256="0" * 64,
        storage_pointer="missing",
        source_uri="missing",
        access_groups=["all_staff"],
        contains_patient_data=True,
        parse_status="parsed",
    )
    case = ReferralCase(
        id="misconfigured-case",
        document_id=document.id,
        status="analysis_ready",
        analysis_json=ReferralAnalysis(document_id=document.id).model_dump(mode="json"),
        model_profile="test_double",
        prompt_version="test",
        created_by=reviewer.id,
    )
    session.add_all([document, case])
    session.commit()

    from backend.app.referral.service import get_referral_case

    with pytest.raises(HTTPException):
        get_referral_case(session, case.id, restricted)

    assert get_referral_case(session, case.id, reviewer).id == case.id


def test_all_staff_user_cannot_read_referral_case_even_if_document_has_all_staff_acl(session):
    restricted = get_current_user("restricted_user")
    reviewer = get_current_user("sekretariat_kardiologie")
    document = Document(
        id="all-staff-document",
        source_system="manual",
        external_id="all-staff",
        title="all staff referral",
        mime_type="text/plain",
        sha256="1" * 64,
        storage_pointer="missing",
        source_uri="missing",
        access_groups=["all_staff"],
        contains_patient_data=True,
        parse_status="parsed",
    )
    case = ReferralCase(
        id="all-staff-case",
        document_id=document.id,
        status="analysis_ready",
        analysis_json=ReferralAnalysis(document_id=document.id).model_dump(mode="json"),
        model_profile="test_double",
        prompt_version="test",
        created_by=reviewer.id,
    )
    session.add_all([document, case])
    session.commit()

    from backend.app.referral.service import get_referral_case

    with pytest.raises(HTTPException):
        get_referral_case(session, case.id, restricted)


def test_all_staff_user_cannot_review_or_writeback_referral_case(session):
    restricted = get_current_user("restricted_user")
    reviewer = get_current_user("sekretariat_kardiologie")
    document = Document(
        id="all-staff-review-document",
        source_system="manual",
        external_id="all-staff-review",
        title="all staff review referral",
        mime_type="text/plain",
        sha256="2" * 64,
        storage_pointer="missing",
        source_uri="missing",
        access_groups=["all_staff"],
        contains_patient_data=True,
        parse_status="parsed",
    )
    case = ReferralCase(
        id="all-staff-review-case",
        document_id=document.id,
        status="analysis_ready",
        analysis_json=ReferralAnalysis(document_id=document.id).model_dump(mode="json"),
        model_profile="test_double",
        prompt_version="test",
        created_by=reviewer.id,
    )
    session.add_all([document, case])
    session.commit()

    from backend.app.referral.review import review_referral_case
    from backend.app.referral.schemas import ReviewRequest
    from backend.app.referral.writeback import writeback_case

    with pytest.raises(HTTPException):
        review_referral_case(session, case.id, restricted, ReviewRequest(decision="confirm"))
    with pytest.raises(HTTPException):
        writeback_case(session, case.id, restricted)


def test_referral_reviewer_can_read_and_review_visible_case(session, tmp_path: Path):
    reviewer = get_current_user("sekretariat_kardiologie")
    sample = tmp_path / "reviewer_visible.txt"
    sample.write_text("Zuweisung wegen Thoraxbeschwerden und Dyspnoe.", encoding="utf-8")
    document = register_file(
        session,
        sample,
        title="reviewer visible",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
    )
    case = analyze_referral(session, document.id, reviewer)

    from backend.app.referral.review import review_referral_case
    from backend.app.referral.schemas import ReviewRequest
    from backend.app.referral.service import get_referral_case

    assert get_referral_case(session, case.id, reviewer).id == case.id
    review = review_referral_case(session, case.id, reviewer, ReviewRequest(decision="confirm"))
    assert review.case_id == case.id


def test_it_admin_can_analyze_and_read_referral_document_without_reviewer_group(session, tmp_path: Path):
    admin = get_current_user("it_admin")
    sample = tmp_path / "admin_visible.txt"
    sample.write_text("Zuweisung wegen Thoraxbeschwerden und Dyspnoe.", encoding="utf-8")
    document = register_file(
        session,
        sample,
        title="admin visible",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
    )

    case = analyze_referral(session, document.id, admin)

    from backend.app.documents.registry import get_visible_document
    from backend.app.referral.service import get_referral_case

    assert get_visible_document(session, document.id, admin).id == document.id
    assert get_referral_case(session, case.id, admin).id == case.id


def test_restricted_user_cannot_list_read_or_analyze_referral_document(
    client: TestClient,
    session,
    tmp_path: Path,
):
    sample = tmp_path / "reviewer_only_referral.txt"
    sample.write_text("Zuweisung wegen Thoraxbeschwerden und Dyspnoe.", encoding="utf-8")

    document = register_file(
        session,
        sample,
        title="reviewer only referral",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
    )

    restricted_headers = {"X-Demo-User": "restricted_user"}
    list_response = client.get("/api/documents", headers=restricted_headers)
    assert list_response.status_code == 200
    assert all(row["id"] != document.id for row in list_response.json())

    read_response = client.get(f"/api/documents/{document.id}", headers=restricted_headers)
    assert read_response.status_code == 403

    analyze_response = client.post(
        f"/api/referrals/analyze/{document.id}",
        headers=restricted_headers,
    )
    assert analyze_response.status_code == 403


def test_sekretariat_can_run_referral_demo_flow(client: TestClient, session, tmp_path: Path):
    sample = tmp_path / "allowed_referral.txt"
    sample.write_text("Zuweisung wegen Thoraxbeschwerden und Dyspnoe.", encoding="utf-8")
    document = register_file(
        session,
        sample,
        title="allowed referral",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
    )

    response = client.post(
        f"/api/referrals/analyze/{document.id}",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
    )

    assert response.status_code == 200
    assert response.json()["document_id"] == document.id


def test_evaluation_api_endpoints_are_not_exposed(client: TestClient):
    assert client.post("/api/referrals/evaluate", headers={"X-Demo-User": "restricted_user"}).status_code in {
        404,
        405,
    }
    assert client.post("/api/guidelines/evaluate", headers={"X-Demo-User": "restricted_user"}).status_code in {
        404,
        405,
    }


def test_admin_audit_requires_admin(client: TestClient):
    response = client.get("/api/admin/audit", headers={"X-Demo-User": "restricted_user"})
    assert response.status_code == 403


def test_admin_audit_allows_admin(client: TestClient):
    response = client.get("/api/admin/audit", headers={"X-Demo-User": "it_admin"})
    assert response.status_code == 200


def test_admin_audit_rejects_non_admin_demo_users(client: TestClient):
    for username in ["hygiene_user", "sekretariat_kardiologie"]:
        response = client.get("/api/admin/audit", headers={"X-Demo-User": username})
        assert response.status_code == 403


def test_unknown_demo_user_fails_closed(client: TestClient):
    response = client.get("/api/documents", headers={"X-Demo-User": "unknown_user"})
    assert response.status_code == 403


def test_guideline_ingest_requires_admin_or_it(client: TestClient):
    response = client.post("/api/guidelines/ingest", headers={"X-Demo-User": "restricted_user"})
    assert response.status_code == 403


def test_guideline_ingest_allows_it_admin(client: TestClient):
    response = client.post("/api/guidelines/ingest", headers={"X-Demo-User": "it_admin"})
    assert response.status_code == 200
