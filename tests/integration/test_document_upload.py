from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

from backend.app.db.models import Document
from backend.app.documents.registry import register_file
from backend.app.main import app


def _pdf_bytes(text: str = "Synthetic referral PDF") -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, invariant=1)
    pdf.drawString(72, 720, text)
    pdf.save()
    return buffer.getvalue()


def test_same_filename_upload_does_not_overwrite(session):
    client = TestClient(app)
    headers = {"X-Demo-User": "sekretariat_kardiologie"}

    first = client.post(
        "/api/documents/upload",
        headers=headers,
        files={"file": ("same.txt", b"first content", "text/plain")},
    )
    second = client.post(
        "/api/documents/upload",
        headers=headers,
        files={"file": ("same.txt", b"second content", "text/plain")},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] != second.json()["id"]
    assert first.json()["sha256"] != second.json()["sha256"]

    documents = session.query(Document).order_by(Document.ingested_at.asc()).all()
    storage_pointers = {document.storage_pointer for document in documents}
    assert len(documents) == 2
    assert len(storage_pointers) == 2
    assert {tuple(document.access_groups) for document in documents} == {("referral_reviewers",)}


def test_unsupported_upload_suffix_is_rejected():
    client = TestClient(app)
    response = client.post(
        "/api/documents/upload",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
        files={"file": ("malware.exe", b"demo", "application/octet-stream")},
    )

    assert response.status_code == 400


def test_unsupported_upload_mime_type_is_rejected():
    client = TestClient(app)
    response = client.post(
        "/api/documents/upload",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
        files={"file": ("demo.txt", b"demo", "application/octet-stream")},
    )

    assert response.status_code == 400


def test_restricted_user_cannot_upload_documents():
    client = TestClient(app)
    response = client.post(
        "/api/documents/upload",
        headers={"X-Demo-User": "restricted_user"},
        files={"file": ("demo.txt", b"demo", "text/plain")},
    )

    assert response.status_code == 403


def test_empty_upload_is_rejected():
    client = TestClient(app)
    response = client.post(
        "/api/documents/upload",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
        files={"file": ("empty.txt", b"", "text/plain")},
    )

    assert response.status_code == 400


def test_oversized_upload_is_rejected():
    client = TestClient(app)
    response = client.post(
        "/api/documents/upload",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
        files={"file": ("large.txt", b"x" * (20 * 1024 * 1024 + 1), "text/plain")},
    )

    assert response.status_code == 400


def test_fake_pdf_upload_is_rejected():
    client = TestClient(app)
    response = client.post(
        "/api/documents/upload",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
        files={"file": ("fake.pdf", b"not a pdf", "application/pdf")},
    )

    assert response.status_code == 400


def test_valid_pdf_upload_is_accepted_and_unsafe_filename_is_sanitized(session):
    client = TestClient(app)
    response = client.post(
        "/api/documents/upload",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
        files={"file": ("../unsafe referral.pdf", _pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "unsafe_referral.pdf"
    document = session.get(Document, payload["id"])
    assert document is not None
    assert document.title == "unsafe_referral.pdf"


def test_reviewer_can_open_original_document_file(session, tmp_path):
    sample = tmp_path / "demo_referral.pdf"
    content = b"%PDF-1.4\n% synthetic demo pdf\n"
    sample.write_bytes(content)
    document = register_file(
        session,
        sample,
        title="Demo Referral",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
        copy_to_uploads=True,
    )

    response = TestClient(app).get(
        f"/api/documents/{document.id}/file",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
    )

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"].startswith("application/pdf")
    assert "inline" in response.headers["content-disposition"]


def test_restricted_user_cannot_open_original_document_file(session, tmp_path):
    sample = tmp_path / "demo_referral.pdf"
    sample.write_bytes(b"%PDF-1.4\n% synthetic demo pdf\n")
    document = register_file(
        session,
        sample,
        title="Demo Referral",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
        copy_to_uploads=True,
    )

    response = TestClient(app).get(
        f"/api/documents/{document.id}/file",
        headers={"X-Demo-User": "restricted_user"},
    )

    assert response.status_code == 403


def test_original_document_outside_approved_storage_roots_is_rejected(session, tmp_path):
    sample = tmp_path / "outside.pdf"
    sample.write_bytes(b"%PDF-1.4\n% synthetic demo pdf\n")
    document = register_file(
        session,
        sample,
        title="Outside Root",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
    )

    response = TestClient(app).get(
        f"/api/documents/{document.id}/file",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
    )

    assert response.status_code == 403
