from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.errors import bad_request
from backend.app.core.time import utc_now
from backend.app.db.models import Document, ReferralCase
from backend.app.documents.object_store import get_object_store_client, object_uri
from backend.app.referral.batch_summary import compute_referral_batch_summary
from backend.app.referral.ingest import iter_source_documents, load_referral_source_config, upsert_source_document
from backend.app.referral.pipeline_events import record_pipeline_event
from backend.app.referral.schemas import (
    ReferralInboxProcessedDocument,
    ReferralInboxProcessResult,
    ReferralInboxSummary,
    ReferralInboxUploadRejected,
    ReferralInboxUploadResult,
)
from backend.app.referral.service import analyze_referral
from backend.app.referral.statuses import (
    PIPELINE_STAGE_INBOX,
    PIPELINE_STATUS_FAILED,
    PIPELINE_STATUS_OK,
    PIPELINE_STATUS_WARNING,
)
from backend.app.security.acl import has_group_overlap, is_admin, require_referral_reviewer
from backend.app.security.auth import DemoUser

PDF_UPLOAD_MIME_TYPES = {"application/pdf", "application/octet-stream", "binary/octet-stream", "application/x-pdf"}


@dataclass(frozen=True)
class InboxUploadFile:
    file_name: str
    content_type: str | None
    content: bytes
    validation_error: str | None = None


def _source_ref(source_document) -> str:
    return str(source_document.storage_uri or source_document.external_id or source_document.path or "")


def _is_pdf_source(source_document) -> bool:
    return Path(_source_ref(source_document)).suffix.lower() == ".pdf"


def _active_inbox_source() -> tuple[str, dict]:
    settings = get_settings()
    config = load_referral_source_config()
    preferred_adapter = settings.referral_inbox_backend
    for source_name, source in config.get("sources", {}).items():
        if source.get("adapter") == preferred_adapter:
            return source_name, source
    for source_name, source in config.get("sources", {}).items():
        if source.get("adapter") in {"filesystem", "minio"}:
            return source_name, source
    raise bad_request("No referral inbox source is configured")


def _source_path(source: dict) -> Path:
    settings = get_settings()
    raw_path = Path(source.get("path") or settings.referral_inbox_dir)
    return raw_path if raw_path.is_absolute() else settings.project_root / raw_path


def _source_backend(source: dict) -> str:
    return "minio" if source.get("adapter") == "minio" else "filesystem"


def _source_label(source: dict) -> str:
    return "MinIO Inbox" if _source_backend(source) == "minio" else "PDF-Inbox"


def _source_location(source: dict) -> str:
    settings = get_settings()
    if _source_backend(source) == "minio":
        bucket = source.get("bucket", settings.object_store_bucket)
        prefix = source.get("prefix", "")
        return f"{bucket}/{prefix}".rstrip("/")
    return str(_source_path(source))


def _visible_source_documents(source_name: str, source: dict, user: DemoUser):
    source_documents = [item for item in iter_source_documents(source_name, source) if _is_pdf_source(item)]
    if is_admin(user):
        return source_documents
    return [item for item in source_documents if has_group_overlap(user, item.access_groups)]


def _registered_documents_by_external_id(session: Session, external_ids: list[str]) -> dict[str, Document]:
    if not external_ids:
        return {}
    rows = (
        session.query(Document)
        .filter(Document.external_id.in_(external_ids))
        .order_by(Document.external_id.asc(), Document.ingested_at.desc())
        .all()
    )
    registered: dict[str, Document] = {}
    for document in rows:
        registered.setdefault(document.external_id, document)
    return registered


def _document_ids_with_cases(session: Session, document_ids: list[str]) -> set[str]:
    if not document_ids:
        return set()
    rows = session.query(ReferralCase.document_id).filter(ReferralCase.document_id.in_(document_ids)).all()
    return {document_id for (document_id,) in rows}


def _summary_from_source_documents(
    session: Session,
    *,
    source_name: str,
    source: dict,
    user: DemoUser,
) -> ReferralInboxSummary:
    settings = get_settings()
    source_documents = _visible_source_documents(source_name, source, user)
    external_ids = [_source_ref(source_document) for source_document in source_documents]
    registered = _registered_documents_by_external_id(session, external_ids)
    analyzed_document_ids = _document_ids_with_cases(session, [document.id for document in registered.values()])
    registered_count = len(registered)
    analyzed_count = len(analyzed_document_ids)
    pending_analysis = max(0, registered_count - analyzed_count)
    unregistered = max(0, len(source_documents) - registered_count)
    return ReferralInboxSummary(
        source_name=source_name,
        backend=_source_backend(source),
        location=_source_location(source),
        bucket=source.get("bucket", settings.object_store_bucket),
        prefix=source.get("prefix", str(_source_path(source)) if _source_backend(source) == "filesystem" else ""),
        total_pdfs=len(source_documents),
        registered_documents=registered_count,
        unregistered_pdfs=unregistered,
        analyzed_documents=analyzed_count,
        pending_analysis=pending_analysis,
        processable_pdfs=unregistered + pending_analysis,
        generated_at=utc_now(),
    )


def get_referral_inbox_summary(session: Session, user: DemoUser) -> ReferralInboxSummary:
    require_referral_reviewer(user)
    source_name, source = _active_inbox_source()
    return _summary_from_source_documents(session, source_name=source_name, source=source, user=user)


def process_referral_inbox(
    session: Session,
    user: DemoUser,
    *,
    limit: int = 2,
) -> ReferralInboxProcessResult:
    require_referral_reviewer(user)
    source_name, source = _active_inbox_source()
    source_documents = _visible_source_documents(source_name, source, user)
    external_ids = [_source_ref(source_document) for source_document in source_documents]
    registered = _registered_documents_by_external_id(session, external_ids)
    analyzed_document_ids = _document_ids_with_cases(session, [document.id for document in registered.values()])

    candidates = []
    for source_document in source_documents:
        external_id = _source_ref(source_document)
        document = registered.get(external_id)
        if document is not None and document.id in analyzed_document_ids:
            continue
        candidates.append(source_document)

    processed: list[ReferralInboxProcessedDocument] = []
    skipped = 0
    attempted_sources = candidates[:limit]
    for source_document in attempted_sources:
        document = None
        try:
            document, decision = upsert_source_document(session, source_document)
            if document is None:
                skipped += 1
                continue
            record_pipeline_event(
                session,
                stage=PIPELINE_STAGE_INBOX,
                status=PIPELINE_STATUS_WARNING if decision == "skipped" else PIPELINE_STATUS_OK,
                message=f"{_source_label(source)}: PDF found {document.title}",
                document_id=document.id,
                payload={"source_system": document.source_system, "decision": decision},
                commit=True,
            )
            case = analyze_referral(session, document.id, user)
            processed.append(
                ReferralInboxProcessedDocument(
                    document_id=document.id,
                    case_id=case.id,
                    document_title=document.title,
                    source_uri=document.source_uri or document.external_id,
                    decision=decision,
                    status=case.status,
                )
            )
        except Exception as exc:
            session.rollback()
            skipped += 1
            record_pipeline_event(
                session,
                stage=PIPELINE_STAGE_INBOX,
                status=PIPELINE_STATUS_FAILED,
                message=f"{_source_label(source)}: PDF processing failed",
                document_id=document.id if document else None,
                payload={
                    "source_system": source.get("source_system", source_name),
                    "source_ref": _source_ref(source_document),
                    "error_type": type(exc).__name__,
                },
                commit=True,
            )

    refreshed_inbox = _summary_from_source_documents(session, source_name=source_name, source=source, user=user)
    return ReferralInboxProcessResult(
        requested_limit=limit,
        processed=len(processed),
        skipped=skipped,
        documents=processed,
        inbox=refreshed_inbox,
        summary=compute_referral_batch_summary(session, user),
    )


def _safe_upload_filename(file_name: str) -> str:
    raw_name = Path(file_name or "referral.pdf").name
    stem = Path(raw_name).stem or "referral"
    suffix = Path(raw_name).suffix.lower() or ".pdf"
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")[:100] or "referral"
    return f"{safe_stem}{suffix}"


def _validate_upload(file: InboxUploadFile, max_bytes: int) -> str | None:
    if file.validation_error:
        return file.validation_error
    file_name = file.file_name or "upload"
    if Path(file_name).suffix.lower() != ".pdf":
        return "Only PDF files are accepted."
    content_type = (file.content_type or "application/octet-stream").split(";", 1)[0].strip().lower()
    if content_type and content_type not in PDF_UPLOAD_MIME_TYPES:
        return f"Unsupported content type: {content_type}"
    if not file.content:
        return "File is empty."
    if len(file.content) > max_bytes:
        return f"File exceeds {max_bytes // (1024 * 1024)} MB upload limit."
    if not file.content.startswith(b"%PDF"):
        return "File does not look like a PDF."
    return None


def _unique_filesystem_path(directory: Path, file_name: str) -> Path:
    candidate = directory / file_name
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    return directory / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"


def _upload_filesystem(source: dict, file_name: str, content: bytes) -> str:
    directory = _source_path(source)
    directory.mkdir(parents=True, exist_ok=True)
    target = _unique_filesystem_path(directory, file_name)
    target.write_bytes(content)
    return target.name


def _upload_minio(source: dict, file_name: str, content: bytes) -> str:
    settings = get_settings()
    bucket = source.get("bucket", settings.object_store_bucket)
    prefix = str(source.get("prefix", "")).strip("/")
    stem = Path(file_name).stem
    suffix = Path(file_name).suffix
    unique_name = f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"
    key = f"{prefix}/{unique_name}".lstrip("/") if prefix else unique_name
    get_object_store_client().upload_object(bucket, key, content, content_type="application/pdf")
    return object_uri(bucket, key)


def upload_referral_inbox_files(
    session: Session,
    user: DemoUser,
    files: list[InboxUploadFile],
) -> ReferralInboxUploadResult:
    require_referral_reviewer(user)
    source_name, source = _active_inbox_source()
    settings = get_settings()
    if len(files) > settings.referral_inbox_max_files:
        raise bad_request(f"Too many files. Limit is {settings.referral_inbox_max_files} files per request.")
    max_bytes = settings.referral_inbox_max_upload_bytes
    uploaded: list[str] = []
    rejected: list[ReferralInboxUploadRejected] = []

    for file in files:
        reason = _validate_upload(file, max_bytes)
        if reason:
            rejected.append(ReferralInboxUploadRejected(file_name=file.file_name or "upload", reason=reason))
            continue
        safe_name = _safe_upload_filename(file.file_name)
        try:
            if _source_backend(source) == "minio":
                stored_ref = _upload_minio(source, safe_name, file.content)
            else:
                stored_ref = _upload_filesystem(source, safe_name, file.content)
        except Exception as exc:
            rejected.append(ReferralInboxUploadRejected(file_name=file.file_name or safe_name, reason=str(exc)))
            continue
        uploaded.append(stored_ref)
        record_pipeline_event(
            session,
            stage=PIPELINE_STAGE_INBOX,
            status=PIPELINE_STATUS_OK,
            message=f"{_source_label(source)}: uploaded {safe_name}",
            payload={"source_system": source.get("source_system", source_name), "decision": "uploaded"},
        )

    session.commit()
    return ReferralInboxUploadResult(
        uploaded=len(uploaded),
        rejected=rejected,
        files=uploaded,
        inbox=_summary_from_source_documents(session, source_name=source_name, source=source, user=user),
    )
