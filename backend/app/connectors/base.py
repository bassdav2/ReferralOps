from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


class SourceDocument(BaseModel):
    external_id: str
    title: str
    path: Path | None = None
    storage_uri: str | None = None
    mime_type: str
    source_system: str
    access_groups: list[str]
    contains_patient_data: bool = False
    sha256: str | None = None
    size_bytes: int | None = None
    etag: str | None = None


class DocumentConnector(Protocol):
    def list_documents(self) -> list[SourceDocument]: ...
