from __future__ import annotations

import re
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.responses import Response

from backend.app.audit.events import AuditPayload
from backend.app.audit.logger import log_event
from backend.app.core.config import get_settings
from backend.app.core.errors import bad_request
from backend.app.db.models import Document
from backend.app.db.session import get_session
from backend.app.documents.registry import (
    get_visible_document,
    original_document_bytes,
    pages_for_document,
    parse_document,
    register_file,
)
from backend.app.security.acl import has_group_overlap, require_referral_reviewer
from backend.app.security.auth import DemoUser, get_current_user
from backend.app.security.groups import GROUP_REFERRAL_REVIEWERS

router = APIRouter(prefix="/api/documents", tags=["documents"])

ALLOWED_UPLOAD_SUFFIXES = {".pdf", ".txt", ".md", ".docx"}
ALLOWED_UPLOAD_MIME_TYPES_BY_SUFFIX = {
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".md": {"text/markdown", "text/plain"},
    ".txt": {"text/plain"},
}


class DocumentRead(BaseModel):
    id: str
    source_system: str
    title: str
    mime_type: str
    sha256: str
    access_groups: list[str]
    contains_patient_data: bool
    parse_status: str


class PageRead(BaseModel):
    page_number: int
    text: str
    ocr_confidence: float | None = None


def _doc_to_read(document: Document) -> DocumentRead:
    return DocumentRead(
        id=document.id,
        source_system=document.source_system,
        title=document.title,
        mime_type=document.mime_type,
        sha256=document.sha256,
        access_groups=document.access_groups,
        contains_patient_data=document.contains_patient_data,
        parse_status=document.parse_status,
    )


def _safe_upload_filename(file_name: str | None) -> str:
    raw_name = Path(file_name or "upload.bin").name
    suffix = Path(raw_name).suffix.lower()
    stem = Path(raw_name).stem or "upload"
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")[:100] or "upload"
    return f"{safe_stem}{suffix}"


def _normalized_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    return content_type.split(";", 1)[0].strip().lower()


def _validate_stored_file_content(path: Path, suffix: str) -> None:
    if suffix == ".pdf":
        with path.open("rb") as handle:
            if handle.read(4) != b"%PDF":
                raise bad_request("Uploaded PDF content does not match the file extension")
        return
    if suffix == ".docx":
        if not zipfile.is_zipfile(path):
            raise bad_request("Uploaded DOCX content does not match the file extension")
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile as exc:
            raise bad_request("Uploaded DOCX content does not match the file extension") from exc
        if "[Content_Types].xml" not in names or not any(name.startswith("word/") for name in names):
            raise bad_request("Uploaded DOCX content does not match the file extension")


@router.get("", response_model=list[DocumentRead])
def list_documents(
    session: Session = Depends(get_session), user: DemoUser = Depends(get_current_user)
) -> list[DocumentRead]:
    rows = session.query(Document).order_by(Document.ingested_at.desc()).all()
    from backend.app.security.acl import is_admin

    visible = [
        row
        for row in rows
        if row.access_groups and (is_admin(user) or has_group_overlap(user, row.access_groups))
    ]
    return [_doc_to_read(row) for row in visible]


@router.post("/upload", response_model=DocumentRead)
def upload_document(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    user: DemoUser = Depends(get_current_user),
) -> DocumentRead:
    settings = get_settings()
    require_referral_reviewer(user)
    safe_name = _safe_upload_filename(file.filename)
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        raise bad_request("Unsupported upload type for demo")
    content_type = _normalized_content_type(file.content_type)
    allowed_mime_types = ALLOWED_UPLOAD_MIME_TYPES_BY_SUFFIX[suffix]
    if content_type and content_type not in allowed_mime_types:
        raise bad_request("Unsupported upload MIME type for demo")

    target = settings.upload_dir / f"{uuid.uuid4().hex}_{safe_name}"
    size = 0
    with target.open("wb") as handle:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.document_upload_max_bytes:
                target.unlink(missing_ok=True)
                raise bad_request("Uploaded file exceeds demo size limit")
            handle.write(chunk)

    if size == 0:
        target.unlink(missing_ok=True)
        raise bad_request("Uploaded file is empty")

    try:
        _validate_stored_file_content(target, suffix)
    except Exception:
        target.unlink(missing_ok=True)
        raise

    document = register_file(
        session,
        target,
        title=safe_name,
        source_system="manual",
        access_groups=[GROUP_REFERRAL_REVIEWERS],
        contains_patient_data=True,
        copy_to_uploads=False,
    )
    parse_document(session, document)
    log_event(
        session,
        user,
        AuditPayload(
            action="document.upload",
            object_type="document",
            object_id=document.id,
            payload_json={"filename": safe_name, "size_bytes": size, "sha256": document.sha256},
        ),
    )
    return _doc_to_read(document)


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(
    document_id: str,
    session: Session = Depends(get_session),
    user: DemoUser = Depends(get_current_user),
) -> DocumentRead:
    return _doc_to_read(get_visible_document(session, document_id, user))


@router.get("/{document_id}/pages", response_model=list[PageRead])
def get_document_pages(
    document_id: str,
    session: Session = Depends(get_session),
    user: DemoUser = Depends(get_current_user),
) -> list[PageRead]:
    document = get_visible_document(session, document_id, user)
    if document.parse_status != "parsed":
        parse_document(session, document)
    return [
        PageRead(page_number=page.page_number, text=page.text, ocr_confidence=page.ocr_confidence)
        for page in pages_for_document(session, document_id)
    ]


@router.get("/{document_id}/file")
def get_document_file(
    document_id: str,
    session: Session = Depends(get_session),
    user: DemoUser = Depends(get_current_user),
) -> Response:
    document = get_visible_document(session, document_id, user)
    title_name = Path(document.title or document.id).name
    suffix = Path(title_name).suffix or Path(document.source_uri or document.external_id or "").suffix or ".pdf"
    filename = title_name if Path(title_name).suffix else f"{title_name}{suffix}"
    quoted_filename = quote(Path(filename).name)
    return Response(
        content=original_document_bytes(document),
        media_type=document.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quoted_filename}"},
    )
