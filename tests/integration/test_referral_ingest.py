from __future__ import annotations

import hashlib
from types import SimpleNamespace

from backend.app.db.models import Document, ReferralCase
from backend.app.documents.object_store import ObjectInfo
from backend.app.referral.inbox_processing import get_referral_inbox_summary, process_referral_inbox
from backend.app.referral.ingest import ingest_referral_sources
from backend.app.referral.schemas import ReferralAnalysis
from backend.app.security.auth import get_current_user


def test_referral_ingest_skips_unchanged_files_and_registers_changed_files(
    isolated_project_root,
    session,
):
    root = isolated_project_root
    referrals = root / "referrals"
    configs = root / "configs"
    referrals.mkdir()

    sample = referrals / "sample.txt"
    sample.write_text("Zuweisung wegen Thoraxbeschwerden und Dyspnoe.", encoding="utf-8")
    (configs / "referral_sources.yml").write_text(
        """
sources:
  test_dropbox:
    adapter: filesystem
    path: referrals
    source_system: test_dropbox
    access_groups: [referral_reviewers]
    contains_patient_data: true
""",
        encoding="utf-8",
    )

    first = ingest_referral_sources(session)
    second = ingest_referral_sources(session)
    sample.write_text("Zuweisung wegen MRI Knie rechts.", encoding="utf-8")
    third = ingest_referral_sources(session)

    assert first == {"documents": 1, "skipped": 0, "changed": 0, "analyses": 0}
    assert second == {"documents": 0, "skipped": 1, "changed": 0, "analyses": 0}
    assert third == {"documents": 1, "skipped": 0, "changed": 1, "analyses": 0}
    assert session.query(Document).filter(Document.source_system == "test_dropbox").count() == 2


def test_referral_ingest_updates_acl_metadata_for_unchanged_files(
    isolated_project_root,
    session,
):
    root = isolated_project_root
    referrals = root / "referrals"
    configs = root / "configs"
    referrals.mkdir()

    sample = referrals / "sample.txt"
    sample.write_text("Zuweisung wegen Thoraxbeschwerden und Dyspnoe.", encoding="utf-8")
    config_path = configs / "referral_sources.yml"
    config_path.write_text(
        """
sources:
  test_dropbox:
    adapter: filesystem
    path: referrals
    source_system: test_dropbox
    access_groups: [kardiologie]
    contains_patient_data: true
""",
        encoding="utf-8",
    )

    assert ingest_referral_sources(session)["documents"] == 1
    document = session.query(Document).filter(Document.source_system == "test_dropbox").one()
    assert document.access_groups == ["kardiologie"]

    config_path.write_text(
        """
sources:
  test_dropbox:
    adapter: filesystem
    path: referrals
    source_system: test_dropbox
    access_groups: [referral_reviewers]
    contains_patient_data: true
""",
        encoding="utf-8",
    )

    result = ingest_referral_sources(session)
    assert result == {"documents": 0, "skipped": 1, "changed": 0, "analyses": 0}
    document = session.query(Document).filter(Document.source_system == "test_dropbox").one()
    assert document.access_groups == ["referral_reviewers"]


def test_referral_ingest_preserves_acl_and_can_analyze_batch(
    isolated_project_root,
    session,
):
    root = isolated_project_root
    referrals = root / "referrals"
    configs = root / "configs"
    referrals.mkdir()

    (referrals / "sample.txt").write_text(
        "Zuweisung wegen Thoraxbeschwerden und Dyspnoe. Medikamentenliste fehlt.",
        encoding="utf-8",
    )
    (configs / "referral_sources.yml").write_text(
        """
sources:
  test_dropbox:
    adapter: filesystem
    path: referrals
    source_system: test_dropbox
    access_groups: [referral_reviewers]
    contains_patient_data: true
    analyze_on_ingest: true
    analyze_user: sekretariat_kardiologie
""",
        encoding="utf-8",
    )

    result = ingest_referral_sources(session)
    document = session.query(Document).filter(Document.source_system == "test_dropbox").one()

    assert result == {"documents": 1, "skipped": 0, "changed": 0, "analyses": 1}
    assert document.access_groups == ["referral_reviewers"]
    assert document.contains_patient_data is True


def test_referral_ingest_report_contains_batch_summary(
    isolated_project_root,
    session,
):
    from fastapi.testclient import TestClient

    from backend.app.main import app

    root = isolated_project_root
    referrals = root / "referrals"
    configs = root / "configs"
    referrals.mkdir()

    (referrals / "sample.txt").write_text(
        "Zuweisung wegen Thoraxbeschwerden und Dyspnoe. Medikamentenliste fehlt.",
        encoding="utf-8",
    )
    (configs / "referral_sources.yml").write_text(
        """
sources:
  test_dropbox:
    adapter: filesystem
    path: referrals
    source_system: test_dropbox
    access_groups: [referral_reviewers]
    contains_patient_data: true
    analyze_on_ingest: true
    analyze_user: sekretariat_kardiologie
""",
        encoding="utf-8",
    )

    response = TestClient(app).post(
        "/api/referrals/ingest-demo-sources",
        headers={"X-Demo-User": "it_admin"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "summary" in payload
    assert set(payload["summary"]) >= {
        "total_documents",
        "analyzed",
        "review_required",
        "routing_distribution",
    }


def test_referral_ingest_registers_minio_objects(isolated_project_root, monkeypatch, session):
    root = isolated_project_root
    configs = root / "configs"
    pdf_bytes = b"%PDF-1.4 synthetic placeholder"
    checksum = hashlib.sha256(pdf_bytes).hexdigest()

    class FakeObjectStoreClient:
        def list_objects(self, bucket: str, prefix: str):
            assert bucket == "documents"
            assert prefix == "referrals/400-demo/"
            return [
                ObjectInfo(key="referrals/400-demo/a_referral.pdf", size_bytes=len(pdf_bytes), etag="etag-a"),
                ObjectInfo(key="referrals/400-demo/preview.png", size_bytes=4, etag="etag-preview"),
            ]

    monkeypatch.setattr(
        "backend.app.connectors.minio.get_object_store_client",
        lambda: FakeObjectStoreClient(),
    )
    monkeypatch.setattr(
        "backend.app.referral.ingest.sha256_object_uri",
        lambda uri: checksum,
    )
    (configs / "referral_sources.yml").write_text(
        """
sources:
  test_minio:
    adapter: minio
    bucket: documents
    prefix: referrals/400-demo/
    source_system: test_minio
    access_groups: [referral_reviewers]
    contains_patient_data: true
""",
        encoding="utf-8",
    )

    result = ingest_referral_sources(session)
    document = session.query(Document).filter(Document.source_system == "test_minio").one()

    assert result == {"documents": 1, "skipped": 0, "changed": 0, "analyses": 0}
    assert document.external_id == "minio://documents/referrals/400-demo/a_referral.pdf"
    assert document.storage_pointer == "minio://documents/referrals/400-demo/a_referral.pdf"
    assert document.sha256 == checksum


def test_referral_inbox_summary_counts_configured_minio_pdfs(
    isolated_project_root,
    monkeypatch,
    session,
):
    root = isolated_project_root
    configs = root / "configs"

    class FakeObjectStoreClient:
        def list_objects(self, bucket: str, prefix: str):
            assert bucket == "documents"
            assert prefix == "referrals/400-demo/"
            return [
                ObjectInfo(key="referrals/400-demo/a_referral.pdf", size_bytes=12, etag="etag-a"),
                ObjectInfo(key="referrals/400-demo/b_referral.pdf", size_bytes=12, etag="etag-b"),
                ObjectInfo(key="referrals/400-demo/preview.png", size_bytes=4, etag="etag-preview"),
            ]

    monkeypatch.setattr(
        "backend.app.connectors.minio.get_object_store_client",
        lambda: FakeObjectStoreClient(),
    )
    (configs / "referral_sources.yml").write_text(
        """
sources:
  test_minio:
    adapter: minio
    bucket: documents
    prefix: referrals/400-demo/
    source_system: test_minio
    access_groups: [referral_reviewers]
    contains_patient_data: true
""",
        encoding="utf-8",
    )

    summary = get_referral_inbox_summary(session, get_current_user("sekretariat_kardiologie"))

    assert summary.total_pdfs == 2
    assert summary.unregistered_pdfs == 2
    assert summary.processable_pdfs == 2


def test_process_referral_inbox_registers_and_analyzes_requested_pdfs(
    isolated_project_root,
    monkeypatch,
    session,
):
    root = isolated_project_root
    configs = root / "configs"
    checksum = hashlib.sha256(b"pdf").hexdigest()

    class FakeObjectStoreClient:
        def list_objects(self, bucket: str, prefix: str):
            return [
                ObjectInfo(key="referrals/400-demo/a_referral.pdf", size_bytes=12, etag="etag-a"),
                ObjectInfo(key="referrals/400-demo/b_referral.pdf", size_bytes=12, etag="etag-b"),
            ]

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

    monkeypatch.setattr(
        "backend.app.connectors.minio.get_object_store_client",
        lambda: FakeObjectStoreClient(),
    )
    monkeypatch.setattr("backend.app.referral.ingest.sha256_object_uri", lambda uri: checksum)
    monkeypatch.setattr("backend.app.referral.inbox_processing.analyze_referral", fake_analyze_referral)
    (configs / "referral_sources.yml").write_text(
        """
sources:
  test_minio:
    adapter: minio
    bucket: documents
    prefix: referrals/400-demo/
    source_system: test_minio
    access_groups: [referral_reviewers]
    contains_patient_data: true
""",
        encoding="utf-8",
    )

    result = process_referral_inbox(session, get_current_user("sekretariat_kardiologie"), limit=1)

    assert result.processed == 1
    assert len(result.documents) == 1
    assert result.documents[0].document_title == "A Referral"
    assert result.inbox.total_pdfs == 2
    assert result.inbox.registered_documents == 1
    assert result.inbox.analyzed_documents == 1
    assert result.inbox.processable_pdfs == 1
