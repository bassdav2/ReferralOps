from __future__ import annotations

import mimetypes
import shutil
import uuid
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.errors import forbidden, not_found
from backend.app.db.models import Document, DocumentPage
from backend.app.documents.acl import validate_document_acl
from backend.app.documents.dedupe import sha256_file
from backend.app.documents.object_store import is_object_uri, object_uri_to_temp_file
from backend.app.documents.ocr import ocr_stub
from backend.app.documents.parser_docx import parse_docx
from backend.app.documents.parser_pdf import ParsedDocument, ParsedPage, parse_pdf, parse_text
from backend.app.security.acl import require_visible
from backend.app.security.auth import DemoUser

TEXT_MIME_TYPES = {"text/plain", "text/markdown", "application/x-yaml"}


def register_file(
    session: Session,
    path: Path,
    *,
    title: str | None = None,
    source_system: str = "manual",
    access_groups: list[str] | None = None,
    contains_patient_data: bool = False,
    copy_to_uploads: bool = False,
) -> Document:
    settings = get_settings()
    validated_access_groups = validate_document_acl(
        access_groups=access_groups,
        contains_patient_data=contains_patient_data,
    )
    source = path
    if copy_to_uploads:
        target = settings.upload_dir / f"{uuid.uuid4().hex}_{path.name}"
        shutil.copyfile(path, target)
        source = target

    document_id = uuid.uuid4().hex
    mime_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    document = Document(
        id=document_id,
        source_system=source_system,
        external_id=str(path),
        title=title or source.stem.replace("_", " ").title(),
        mime_type=mime_type,
        sha256=sha256_file(source),
        storage_pointer=str(source),
        source_uri=str(path),
        access_groups=validated_access_groups,
        contains_patient_data=contains_patient_data,
        parse_status="pending",
    )
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def register_object_document(
    session: Session,
    storage_uri: str,
    *,
    title: str,
    mime_type: str,
    sha256: str,
    external_version: str | None = None,
    source_system: str = "minio",
    access_groups: list[str] | None = None,
    contains_patient_data: bool = False,
) -> Document:
    validated_access_groups = validate_document_acl(
        access_groups=access_groups,
        contains_patient_data=contains_patient_data,
    )
    document = Document(
        id=uuid.uuid4().hex,
        source_system=source_system,
        external_id=storage_uri,
        external_version=external_version,
        title=title,
        mime_type=mime_type,
        sha256=sha256,
        storage_pointer=storage_uri,
        source_uri=storage_uri,
        access_groups=validated_access_groups,
        contains_patient_data=contains_patient_data,
        parse_status="pending",
    )
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def get_visible_document(session: Session, document_id: str, user: DemoUser) -> Document:
    document = session.get(Document, document_id)
    if not document:
        raise not_found("Document not found")
    require_visible(user, document.access_groups)
    return document


def _first_existing_document_path(document: Document) -> Path | None:
    for raw in (document.storage_pointer, document.source_uri, document.external_id):
        if not raw:
            continue
        path = Path(raw)
        if path.exists():
            return path
    return None


def _approved_local_storage_roots() -> list[Path]:
    settings = get_settings()
    roots = [
        settings.upload_dir,
        settings.referral_inbox_dir,
        settings.demo_preload_referrals_dir,
    ]
    try:
        from backend.app.referral.ingest import load_referral_source_config

        for source in load_referral_source_config().get("sources", {}).values():
            if source.get("adapter") != "filesystem":
                continue
            raw_path = source.get("path")
            if not raw_path:
                continue
            path = Path(raw_path)
            roots.append(path if path.is_absolute() else settings.project_root / path)
    except (OSError, KeyError, TypeError, ValueError):
        pass
    return [root.resolve() for root in roots]


def _is_under_root(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    return resolved == root or root in resolved.parents


def _first_allowed_existing_document_path(document: Document) -> Path | None:
    path = _first_existing_document_path(document)
    if path is None:
        return None
    roots = _approved_local_storage_roots()
    if any(_is_under_root(path, root) for root in roots):
        return path
    raise forbidden("Original document path is outside approved storage roots")


def _first_object_uri(document: Document) -> str | None:
    for raw in (document.storage_pointer, document.source_uri, document.external_id):
        if is_object_uri(raw):
            return raw
    return None


def _parse_path(document: Document, path: Path) -> ParsedDocument:
    if document.mime_type == "application/pdf" or path.suffix.lower() == ".pdf":
        return parse_pdf(path)
    if path.suffix.lower() == ".docx":
        return parse_docx(path)
    if document.mime_type in TEXT_MIME_TYPES or path.suffix.lower() in {".txt", ".md", ".yml", ".yaml"}:
        return parse_text(path)
    return ocr_stub(path)


def _replace_document_pages(session: Session, document: Document, parsed: ParsedDocument) -> None:
    session.execute(delete(DocumentPage).where(DocumentPage.document_id == document.id))
    for page in parsed.pages:
        session.add(
            DocumentPage(
                document_id=document.id,
                page_number=page.page_number,
                text=page.text,
                ocr_confidence=page.ocr_confidence,
            )
        )
    document.parse_status = "parsed"


def parse_document(session: Session, document: Document) -> ParsedDocument:
    missing_path = Path(document.storage_pointer or document.source_uri or document.external_id or "")
    object_storage_uri = _first_object_uri(document)
    if object_storage_uri:
        with object_uri_to_temp_file(object_storage_uri) as path:
            parsed = _parse_path(document, path)
        _replace_document_pages(session, document, parsed)
        session.commit()
        return parsed

    path = _first_existing_document_path(document)
    if path is None:
        cached_pages = pages_for_document(session, document.id)
        if cached_pages:
            return ParsedDocument(
                pages=[
                    ParsedPage(
                        page_number=page.page_number,
                        text=page.text,
                        ocr_confidence=page.ocr_confidence,
                    )
                    for page in cached_pages
                ]
            )
        parsed = ocr_stub(missing_path)
    else:
        parsed = _parse_path(document, path)

    _replace_document_pages(session, document, parsed)
    session.commit()
    return parsed


def pages_for_document(session: Session, document_id: str) -> list[DocumentPage]:
    return (
        session.query(DocumentPage)
        .filter(DocumentPage.document_id == document_id)
        .order_by(DocumentPage.page_number.asc())
        .all()
    )


def original_document_bytes(document: Document) -> bytes:
    object_storage_uri = _first_object_uri(document)
    if object_storage_uri:
        with object_uri_to_temp_file(object_storage_uri) as path:
            return path.read_bytes()

    path = _first_allowed_existing_document_path(document)
    if path is None:
        raise not_found("Original document file is not available")
    return path.read_bytes()
