from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.app.db.models import Document, DocumentPage, ReferralCase, ReferralPipelineEvent, ReferralReview
from backend.app.referral.inbox_processing import process_referral_inbox
from backend.app.referral.schemas import ReferralAnalysis
from backend.app.security.auth import get_current_user

PDF_BYTES = b"%PDF-1.4\n% synthetic test pdf\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def test_upload_pdf_into_filesystem_inbox(isolated_project_root, session):
    from backend.app.main import app

    response = TestClient(app).post(
        "/api/referrals/inbox/upload",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
        files=[("files", ("demo_referral.pdf", PDF_BYTES, "application/pdf"))],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["uploaded"] == 1
    assert payload["rejected"] == []
    assert payload["inbox"]["backend"] == "filesystem"
    assert payload["inbox"]["total_pdfs"] == 1
    assert payload["inbox"]["processable_pdfs"] == 1
    assert (isolated_project_root / "data" / "referral_inbox" / "demo_referral.pdf").exists()


def test_upload_rejects_non_pdf_files(isolated_project_root):
    from backend.app.main import app

    response = TestClient(app).post(
        "/api/referrals/inbox/upload",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
        files=[("files", ("notes.txt", b"hello", "text/plain"))],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["uploaded"] == 0
    assert payload["rejected"][0]["file_name"] == "notes.txt"
    assert "Only PDF" in payload["rejected"][0]["reason"]


def test_upload_rejects_oversized_pdf_before_processing(
    isolated_project_root, monkeypatch, reset_runtime_caches
):
    from backend.app.main import app

    monkeypatch.setenv("REFERRAL_INBOX_MAX_UPLOAD_BYTES", "16")
    reset_runtime_caches()

    response = TestClient(app).post(
        "/api/referrals/inbox/upload",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
        files=[("files", ("too_large.pdf", PDF_BYTES, "application/pdf"))],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["uploaded"] == 0
    assert "exceeds" in payload["rejected"][0]["reason"]


def test_upload_rejects_too_many_files(isolated_project_root, monkeypatch, reset_runtime_caches):
    from backend.app.main import app

    monkeypatch.setenv("REFERRAL_INBOX_MAX_FILES", "1")
    reset_runtime_caches()

    response = TestClient(app).post(
        "/api/referrals/inbox/upload",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
        files=[
            ("files", ("one.pdf", PDF_BYTES, "application/pdf")),
            ("files", ("two.pdf", PDF_BYTES, "application/pdf")),
        ],
    )

    assert response.status_code == 400


def test_restricted_user_cannot_upload_to_referral_inbox(isolated_project_root):
    from backend.app.main import app

    response = TestClient(app).post(
        "/api/referrals/inbox/upload",
        headers={"X-Demo-User": "restricted_user"},
        files=[("files", ("demo_referral.pdf", PDF_BYTES, "application/pdf"))],
    )

    assert response.status_code == 403


def test_demo_reset_clears_filesystem_inbox_and_referral_state(isolated_project_root, session):
    from backend.app.main import app

    client = TestClient(app)
    upload_response = client.post(
        "/api/referrals/inbox/upload",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
        files=[("files", ("demo_referral.pdf", PDF_BYTES, "application/pdf"))],
    )
    assert upload_response.status_code == 200

    document = Document(
        id="doc-reset-test",
        source_system="demo_referral_filesystem",
        external_id="file://demo_referral.pdf",
        title="Reset Test",
        mime_type="application/pdf",
        sha256="0" * 64,
        access_groups=["referral_reviewers", "kardiologie"],
        contains_patient_data=True,
    )
    case = ReferralCase(
        id="case-reset-test",
        document_id=document.id,
        status="analysis_ready",
        analysis_json=ReferralAnalysis(document_id=document.id).model_dump(mode="json"),
        model_profile="test_double",
        prompt_version="test",
        created_by="sekretariat_kardiologie",
    )
    session.add(document)
    session.add(DocumentPage(document_id=document.id, page_number=1, text="demo", ocr_confidence=None))
    session.add(case)
    session.add(
        ReferralReview(
            id="review-reset-test",
            case_id=case.id,
            reviewer_id="sekretariat_kardiologie",
            decision="confirm",
            corrected_json=None,
            comment=None,
        )
    )
    session.add(
        ReferralPipelineEvent(
            id="event-reset-test",
            document_id=document.id,
            case_id=case.id,
            stage="worklist",
            status="completed",
            message="Available in review worklist",
            payload_json=None,
        )
    )
    unrelated = Document(
        id="doc-not-demo-reset",
        source_system="manual",
        external_id="manual-doc",
        title="Manual Upload Should Remain",
        mime_type="text/plain",
        sha256="1" * 64,
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
        parse_status="parsed",
    )
    session.add(unrelated)
    session.add(DocumentPage(document_id=unrelated.id, page_number=1, text="manual", ocr_confidence=None))
    session.commit()

    response = client.post("/api/referrals/demo-reset", headers={"X-Demo-User": "it_admin"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["documents_deleted"] == 1
    assert payload["cases_deleted"] == 1
    assert payload["reviews_deleted"] == 1
    assert payload["events_deleted"] >= 1
    assert payload["inbox_files_deleted"] == 1
    assert payload["inbox"]["total_pdfs"] == 0
    assert payload["summary"]["total_documents"] == 1
    assert session.get(Document, unrelated.id) is not None
    assert not (isolated_project_root / "data" / "referral_inbox" / "demo_referral.pdf").exists()


def test_restricted_user_cannot_reset_demo_dashboard(isolated_project_root):
    from backend.app.main import app

    response = TestClient(app).post(
        "/api/referrals/demo-reset",
        headers={"X-Demo-User": "restricted_user"},
    )

    assert response.status_code == 403


def test_referral_reviewer_cannot_reset_demo_dashboard(isolated_project_root):
    from backend.app.main import app

    response = TestClient(app).post(
        "/api/referrals/demo-reset",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
    )

    assert response.status_code == 403


def test_process_filesystem_inbox_without_minio(isolated_project_root, monkeypatch, session):
    inbox = isolated_project_root / "data" / "referral_inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "demo_referral.pdf").write_bytes(PDF_BYTES)

    def fake_analyze_referral(db_session, document_id: str, user):
        case = ReferralCase(
            id=f"case-{document_id[:8]}",
            document_id=document_id,
            status="analysis_ready",
            analysis_json=ReferralAnalysis(document_id=document_id).model_dump(mode="json"),
            model_profile="test_double",
            prompt_version="test",
            created_by=user.id,
        )
        db_session.add(case)
        db_session.commit()
        return SimpleNamespace(id=case.id, status=case.status)

    monkeypatch.setattr("backend.app.referral.inbox_processing.analyze_referral", fake_analyze_referral)

    result = process_referral_inbox(session, get_current_user("sekretariat_kardiologie"), limit=1)

    assert result.inbox.backend == "filesystem"
    assert result.processed == 1
    assert result.documents[0].document_title == "Demo Referral"
    assert session.query(Document).filter(Document.source_system == "demo_referral_filesystem").count() == 1
