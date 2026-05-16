from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db.models import Document, DocumentPage, ReferralCase, ReferralPipelineEvent, ReferralReview
from backend.app.documents.object_store import get_object_store_client
from backend.app.referral.batch_summary import compute_referral_batch_summary
from backend.app.referral.demo_outputs import ensure_demo_output_folders
from backend.app.referral.inbox_processing import (
    _active_inbox_source,
    _source_backend,
    _source_path,
    get_referral_inbox_summary,
)
from backend.app.referral.schemas import ReferralDemoResetResult
from backend.app.security.acl import require_admin
from backend.app.security.auth import DemoUser


def _delete_filesystem_inbox_files(source: dict) -> int:
    inbox_dir = _source_path(source)
    if not inbox_dir.exists():
        inbox_dir.mkdir(parents=True, exist_ok=True)
        return 0
    deleted = 0
    for path in inbox_dir.iterdir():
        if path.name == ".gitkeep":
            continue
        if path.is_file():
            path.unlink()
            deleted += 1
    (inbox_dir / ".gitkeep").touch()
    return deleted


def _delete_minio_inbox_files(source: dict) -> int:
    settings = get_settings()
    bucket = source.get("bucket", settings.object_store_bucket)
    prefix = str(source.get("prefix", "")).strip("/")
    client = get_object_store_client()
    deleted = 0
    for item in client.list_objects(bucket, prefix):
        if not Path(item.key).suffix.lower() == ".pdf":
            continue
        client.delete_object(bucket, item.key)
        deleted += 1
    return deleted


def _delete_demo_output_json() -> int:
    base_dir = ensure_demo_output_folders()
    deleted = 0
    for path in base_dir.rglob("*.json"):
        path.unlink()
        deleted += 1
    return deleted


def reset_referral_demo_state(session: Session, user: DemoUser) -> ReferralDemoResetResult:
    require_admin(user)
    source_name, source = _active_inbox_source()
    source_systems = {source.get("source_system", source_name)}

    if _source_backend(source) == "minio":
        inbox_files_deleted = _delete_minio_inbox_files(source)
    else:
        inbox_files_deleted = _delete_filesystem_inbox_files(source)

    output_files_deleted = _delete_demo_output_json()

    document_ids = [
        document_id
        for (document_id,) in session.query(Document.id).filter(Document.source_system.in_(source_systems)).all()
    ]
    case_ids = [
        case_id
        for (case_id,) in session.query(ReferralCase.id).filter(ReferralCase.document_id.in_(document_ids)).all()
    ] if document_ids else []

    events_deleted = 0
    for event in session.query(ReferralPipelineEvent).all():
        payload_source_system = (event.payload_json or {}).get("source_system")
        if event.document_id in document_ids or event.case_id in case_ids or payload_source_system in source_systems:
            session.delete(event)
            events_deleted += 1

    reviews_deleted = (
        session.query(ReferralReview).filter(ReferralReview.case_id.in_(case_ids)).delete(synchronize_session=False)
        if case_ids
        else 0
    )
    cases_deleted = (
        session.query(ReferralCase).filter(ReferralCase.id.in_(case_ids)).delete(synchronize_session=False)
        if case_ids
        else 0
    )
    pages_deleted = (
        session.query(DocumentPage).filter(DocumentPage.document_id.in_(document_ids)).delete(synchronize_session=False)
        if document_ids
        else 0
    )
    documents_deleted = (
        session.query(Document).filter(Document.id.in_(document_ids)).delete(synchronize_session=False)
        if document_ids
        else 0
    )
    session.commit()

    return ReferralDemoResetResult(
        documents_deleted=documents_deleted,
        pages_deleted=pages_deleted,
        cases_deleted=cases_deleted,
        reviews_deleted=reviews_deleted,
        events_deleted=events_deleted,
        inbox_files_deleted=inbox_files_deleted,
        output_files_deleted=output_files_deleted,
        inbox=get_referral_inbox_summary(session, user),
        summary=compute_referral_batch_summary(session, user),
    )
