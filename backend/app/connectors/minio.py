from __future__ import annotations

import mimetypes
from pathlib import Path

from backend.app.connectors.base import SourceDocument
from backend.app.core.config import get_settings
from backend.app.documents.object_store import get_object_store_client, object_uri


def list_minio_documents(
    *,
    bucket: str | None = None,
    prefix: str = "",
    access_groups: list[str],
    source_system: str = "minio",
    contains_patient_data: bool = False,
) -> list[SourceDocument]:
    settings = get_settings()
    bucket_name = bucket or settings.object_store_bucket
    normalized_prefix = prefix.lstrip("/")
    objects = get_object_store_client().list_objects(bucket_name, normalized_prefix)
    documents: list[SourceDocument] = []
    for item in objects:
        if item.key.endswith("/"):
            continue
        mime_type = mimetypes.guess_type(item.key)[0] or "application/octet-stream"
        documents.append(
            SourceDocument(
                external_id=object_uri(bucket_name, item.key),
                title=Path(item.key).stem.replace("_", " ").title(),
                storage_uri=object_uri(bucket_name, item.key),
                mime_type=mime_type,
                source_system=source_system,
                access_groups=access_groups,
                contains_patient_data=contains_patient_data,
                size_bytes=item.size_bytes,
                etag=item.etag,
            )
        )
    return documents
