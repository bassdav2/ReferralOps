from __future__ import annotations

import random
from pathlib import Path

import httpx
import yaml
from sqlalchemy.orm import Session

from backend.app.connectors.factory import connector_factory
from backend.app.core.config import get_settings
from backend.app.db.models import Document
from backend.app.documents.acl import validate_document_acl
from backend.app.documents.dedupe import sha256_file
from backend.app.documents.object_store import sha256_object_uri
from backend.app.documents.registry import register_file, register_object_document
from backend.app.referral.batch_summary import compute_referral_batch_summary
from backend.app.referral.pipeline_events import record_pipeline_event
from backend.app.referral.service import analyze_referral
from backend.app.referral.statuses import PIPELINE_STAGE_INBOX, PIPELINE_STATUS_OK, PIPELINE_STATUS_WARNING
from backend.app.security.acl import is_admin
from backend.app.security.auth import DemoUser, get_current_user
from backend.app.security.groups import GROUP_ADMIN, GROUP_REFERRAL_REVIEWERS

ALLOWED_REFERRAL_SUFFIXES = {".pdf", ".txt", ".md", ".docx"}


def _require_source_access_groups(source_name: str, source: dict) -> list[str]:
    groups = source.get("access_groups")
    if not groups:
        raise ValueError(f"Referral source {source_name} requires explicit access_groups")
    return groups


def load_referral_source_config() -> dict:
    settings = get_settings()
    config_path = settings.project_root / "configs" / "referral_sources.yml"
    configured = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {"sources": {}}
    sources = configured.get("sources") or {}
    active_backend = settings.referral_inbox_backend
    matching_sources = {
        name: source
        for name, source in sources.items()
        if source.get("adapter") == active_backend
    }
    if matching_sources:
        configured["sources"] = matching_sources
        return configured
    if sources:
        return configured
    configured["sources"] = {
        "demo_referral_filesystem": {
            "adapter": "filesystem",
            "path": str(settings.referral_inbox_dir),
            "source_system": "demo_referral_filesystem",
            "access_groups": [GROUP_REFERRAL_REVIEWERS],
            "contains_patient_data": True,
            "default_status": "active",
            "analyze_on_ingest": False,
            "analyze_user": "sekretariat_kardiologie",
        }
    }
    return configured


def _limited_source_documents(documents, source: dict):
    selected = list(documents)
    sample_count = source.get("sample_documents")
    if sample_count is not None:
        rng = random.Random(int(source.get("sample_seed", 42)))
        rng.shuffle(selected)
        selected = selected[: int(sample_count)]
    limit = source.get("max_documents")
    for index, source_document in enumerate(selected):
        if limit is not None and index >= int(limit):
            break
        yield source_document


def iter_source_documents(source_name: str, source: dict):
    settings = get_settings()
    connector = connector_factory(source)
    common = {
        "access_groups": _require_source_access_groups(source_name, source),
        "source_system": source.get("source_system", source_name),
        "contains_patient_data": source.get("contains_patient_data", True),
    }
    if source.get("adapter") == "minio":
        yield from _limited_source_documents(
            connector(
                bucket=source.get("bucket", settings.object_store_bucket),
                prefix=source.get("prefix", ""),
                **common,
            ),
            source,
        )
        return

    raw_path = Path(source["path"])
    path = raw_path if raw_path.is_absolute() else settings.project_root / raw_path
    yield from _limited_source_documents(connector(path, **common), source)


def upsert_source_document(session: Session, source_document) -> tuple[Document | None, str]:
    source_ref = source_document.storage_uri or source_document.path
    if source_ref is None:
        return None, "ignored"
    if Path(str(source_ref)).suffix.lower() not in ALLOWED_REFERRAL_SUFFIXES:
        return None, "ignored"

    access_groups = validate_document_acl(
        access_groups=source_document.access_groups,
        contains_patient_data=source_document.contains_patient_data,
    )
    existing = (
        session.query(Document)
        .filter(
            Document.source_system == source_document.source_system,
            Document.external_id == source_document.external_id,
        )
        .order_by(Document.ingested_at.desc())
        .first()
    )
    if existing and source_document.etag and existing.external_version in {source_document.etag, None}:
        existing.external_version = source_document.etag
        existing.access_groups = access_groups
        existing.contains_patient_data = source_document.contains_patient_data
        session.commit()
        return existing, "skipped"

    if source_document.sha256:
        checksum = source_document.sha256
    elif source_document.path is not None:
        checksum = sha256_file(source_document.path)
    else:
        checksum = sha256_object_uri(source_document.storage_uri)

    if existing and existing.sha256 == checksum:
        existing.access_groups = access_groups
        existing.contains_patient_data = source_document.contains_patient_data
        existing.external_version = source_document.etag or existing.external_version
        session.commit()
        return existing, "skipped"

    if source_document.storage_uri:
        document = register_object_document(
            session,
            source_document.storage_uri,
            title=source_document.title,
            mime_type=source_document.mime_type,
            sha256=checksum,
            external_version=source_document.etag,
            source_system=source_document.source_system,
            access_groups=access_groups,
            contains_patient_data=source_document.contains_patient_data,
        )
    else:
        document = register_file(
            session,
            source_document.path,
            title=source_document.title,
            source_system=source_document.source_system,
            access_groups=access_groups,
            contains_patient_data=source_document.contains_patient_data,
            copy_to_uploads=True,
        )
    return document, "changed" if existing else "created"


def maybe_analyze_ingested_document(session: Session, document: Document, source: dict) -> bool:
    if not source.get("analyze_on_ingest", False):
        return False
    user = get_current_user(source.get("analyze_user", "sekretariat_kardiologie"))
    analyze_referral(session, document.id, user)
    return True


def ingest_referral_sources(session: Session) -> dict:
    config = load_referral_source_config()

    documents = 0
    skipped = 0
    changed = 0
    analyses = 0
    for source_name, source in config["sources"].items():
        try:
            source_documents = list(iter_source_documents(source_name, source))
        except (httpx.HTTPError, OSError) as exc:
            inbox_label = "MinIO Inbox" if source.get("adapter") == "minio" else "PDF-Inbox"
            record_pipeline_event(
                session,
                stage=PIPELINE_STAGE_INBOX,
                status=PIPELINE_STATUS_WARNING,
                message=f"{inbox_label}: source unavailable {source_name}",
                payload={"source_system": source.get("source_system", source_name), "error_type": type(exc).__name__},
            )
            continue
        for source_document in source_documents:
            document, decision = upsert_source_document(session, source_document)
            if decision == "ignored":
                continue
            if document is not None:
                inbox_label = (
                    "MinIO Inbox"
                    if source.get("adapter") == "minio" or source_document.storage_uri
                    else "PDF-Inbox"
                )
                record_pipeline_event(
                    session,
                    stage=PIPELINE_STAGE_INBOX,
                    status=PIPELINE_STATUS_WARNING if decision == "skipped" else PIPELINE_STATUS_OK,
                    message=f"{inbox_label}: PDF found {document.title}",
                    document_id=document.id,
                    payload={"source_system": document.source_system, "decision": decision},
                )
            if decision == "skipped":
                skipped += 1
            elif decision == "changed":
                changed += 1
                documents += 1
            elif decision == "created":
                documents += 1
            if document is not None and decision in {"created", "changed"} and maybe_analyze_ingested_document(
                session, document, source
            ):
                analyses += 1

    session.commit()
    return {"documents": documents, "skipped": skipped, "changed": changed, "analyses": analyses}


def ingest_referral_sources_report(session: Session, user: DemoUser) -> dict:
    result = ingest_referral_sources(session)
    summary_user = user
    if not (set(user.groups).intersection({GROUP_REFERRAL_REVIEWERS, GROUP_ADMIN}) or is_admin(user)):
        summary_user = get_current_user("sekretariat_kardiologie")
    elif GROUP_REFERRAL_REVIEWERS not in user.groups and is_admin(user):
        summary_user = get_current_user("sekretariat_kardiologie")
    return {**result, "summary": compute_referral_batch_summary(session, summary_user)}
