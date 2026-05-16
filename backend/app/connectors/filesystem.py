from __future__ import annotations

import mimetypes
from pathlib import Path

from backend.app.connectors.base import SourceDocument


def list_filesystem_documents(
    path: Path,
    *,
    access_groups: list[str],
    source_system: str = "filesystem",
    contains_patient_data: bool = False,
) -> list[SourceDocument]:
    paths = sorted(path.glob("*")) if path.is_dir() else [path]
    documents: list[SourceDocument] = []
    for item in paths:
        if not item.is_file():
            continue
        mime_type = mimetypes.guess_type(item.name)[0] or "text/plain"
        documents.append(
            SourceDocument(
                external_id=str(item),
                title=item.stem.replace("_", " ").title(),
                path=item,
                mime_type=mime_type,
                source_system=source_system,
                access_groups=access_groups,
                contains_patient_data=contains_patient_data,
            )
        )
    return documents

