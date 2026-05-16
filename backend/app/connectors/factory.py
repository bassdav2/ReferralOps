from __future__ import annotations

from backend.app.connectors.filesystem import list_filesystem_documents
from backend.app.connectors.minio import list_minio_documents


def connector_factory(source: dict):
    adapter = source.get("adapter")
    if adapter == "filesystem":
        return list_filesystem_documents
    if adapter == "minio":
        return list_minio_documents
    raise ValueError(f"Unsupported connector adapter: {adapter}")
