from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from backend.app.db.models import Document
from backend.app.documents.registry import parse_document


def _pdf_with_lines(path: Path, lines: list[str]) -> None:
    pdf = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    _, height = A4
    y = height - 72
    pdf.setFont("Helvetica", 11)
    for line in lines:
        pdf.drawString(72, y, line)
        y -= 20
    pdf.save()


def test_parse_document_downloads_minio_object(monkeypatch, session, tmp_path: Path):
    source_pdf = tmp_path / "source.pdf"
    _pdf_with_lines(
        source_pdf,
        [
            "Synthetische Zuweisung Kardiologie",
            "Grund: Thoraxbeschwerden und Dyspnoe bei Belastung.",
            "Hinweis: Demo-Daten, keine echte Person.",
        ],
    )

    class FakeObjectStoreClient:
        def download_object(self, bucket: str, key: str, target: Path) -> None:
            assert bucket == "documents"
            assert key == "referrals/400-demo/source.pdf"
            target.write_bytes(source_pdf.read_bytes())

    monkeypatch.setattr(
        "backend.app.documents.object_store.get_object_store_client",
        lambda: FakeObjectStoreClient(),
    )
    document = Document(
        id="minio-parse-document",
        source_system="test_minio",
        external_id="minio://documents/referrals/400-demo/source.pdf",
        title="source",
        mime_type="application/pdf",
        sha256="0" * 64,
        storage_pointer="minio://documents/referrals/400-demo/source.pdf",
        source_uri="minio://documents/referrals/400-demo/source.pdf",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
        parse_status="pending",
    )
    session.add(document)
    session.commit()

    parsed = parse_document(session, document)

    assert "Thoraxbeschwerden" in parsed.text
    assert document.parse_status == "parsed"
