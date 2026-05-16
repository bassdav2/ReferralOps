from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import yaml
from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db.models import GuidelineChunk, GuidelineDocument
from backend.app.documents.chunking import chunk_markdown
from backend.app.model_gateway import get_embedding_client


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_guideline_source_config() -> dict:
    settings = get_settings()
    config_path = settings.project_root / "configs" / "guideline_sources.yml"
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))


def iter_guideline_paths(source: dict) -> list[Path]:
    settings = get_settings()
    raw_path = Path(source["path"])
    path = raw_path if raw_path.is_absolute() else settings.project_root / raw_path
    return sorted(path.glob("*")) if path.is_dir() else [path]


def _require_access_groups(source_name: str, source: dict) -> list[str]:
    groups = source.get("access_groups")
    if not groups:
        raise ValueError(f"Guideline source {source_name} requires explicit access_groups")
    return groups


def upsert_guideline_document(
    session: Session,
    *,
    source_name: str,
    source: dict,
    document_path: Path,
) -> tuple[GuidelineDocument, str]:
    external_id = f"{source_name}:{document_path.name}"
    checksum = _checksum(document_path)
    access_groups = _require_access_groups(source_name, source)
    existing = (
        session.query(GuidelineDocument)
        .filter(GuidelineDocument.external_id == external_id)
        .one_or_none()
    )
    if existing and existing.checksum == checksum:
        document = existing
        decision = "skipped"
    elif existing:
        session.execute(delete(GuidelineChunk).where(GuidelineChunk.document_id == existing.id))
        document = existing
        decision = "changed"
    else:
        document = GuidelineDocument(
            id=uuid.uuid4().hex,
            source_system=source.get("adapter", "filesystem"),
            external_id=external_id,
            title=document_path.stem.replace("_", " ").title(),
            owner_department=source.get("owner_department", "Unknown"),
            version=source.get("version", "demo-v1"),
            status=source.get("default_status", "active"),
            access_groups=access_groups,
            escalation_contact=source.get("escalation_contact"),
            source_uri=str(document_path),
            checksum=checksum,
        )
        session.add(document)
        session.flush()
        decision = "created"

    document.title = document_path.stem.replace("_", " ").title()
    document.owner_department = source.get("owner_department", "Unknown")
    document.version = source.get("version", "demo-v1")
    document.status = source.get("default_status", "active")
    document.access_groups = access_groups
    document.escalation_contact = source.get("escalation_contact")
    document.source_uri = str(document_path)
    document.checksum = checksum
    return document, decision


def replace_guideline_chunks(session: Session, document: GuidelineDocument, text: str) -> int:
    embeddings = get_embedding_client()
    chunks = chunk_markdown(text)
    vectors = embeddings.embed_documents([chunk.text for chunk in chunks])
    for chunk, vector in zip(chunks, vectors, strict=True):
        session.add(
            GuidelineChunk(
                id=uuid.uuid4().hex,
                document_id=document.id,
                heading_path=chunk.heading_path,
                chunk_text=chunk.text,
                token_count=len(chunk.text.split()),
                embedding=vector,
                page=chunk.page,
                order_index=chunk.order_index,
            )
        )
    return len(chunks)


def ingest_guideline_sources(session: Session) -> dict:
    config = load_guideline_source_config()
    created = 0
    changed = 0
    skipped = 0
    chunks_written = 0

    for source_name, source in config["sources"].items():
        for document_path in iter_guideline_paths(source):
            if not document_path.is_file():
                continue
            document, decision = upsert_guideline_document(
                session,
                source_name=source_name,
                source=source,
                document_path=document_path,
            )
            if decision == "skipped":
                skipped += 1
                continue
            if decision == "changed":
                changed += 1
            else:
                created += 1

            text = document_path.read_text(encoding="utf-8")
            chunks_written += replace_guideline_chunks(session, document, text)
    session.commit()
    documents_written = created + changed
    return {
        "documents": documents_written,
        "chunks": chunks_written,
        "chunks_written": chunks_written,
        "created": created,
        "changed": changed,
        "skipped": skipped,
    }
