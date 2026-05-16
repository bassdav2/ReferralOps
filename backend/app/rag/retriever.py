from __future__ import annotations

import math

from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db.models import GuidelineChunk, GuidelineDocument
from backend.app.rag.schemas import RetrievedChunk
from backend.app.rag.tokenization import content_terms
from backend.app.security.acl import has_group_overlap
from backend.app.security.auth import DemoUser


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def search_chunks(
    session: Session,
    *,
    query: str,
    query_vector: list[float],
    user: DemoUser,
    top_k: int = 20,
) -> list[RetrievedChunk]:
    settings = get_settings()
    question_tokens = content_terms(query)
    rows = (
        session.query(GuidelineChunk, GuidelineDocument)
        .join(GuidelineDocument, GuidelineChunk.document_id == GuidelineDocument.id)
        .filter(GuidelineDocument.status == "active")
        .all()
    )
    scored: list[RetrievedChunk] = []
    for chunk, document in rows:
        if not has_group_overlap(user, document.access_groups):
            continue
        chunk_tokens = content_terms(chunk.chunk_text + " " + document.title + " " + " ".join(chunk.heading_path))
        lexical = len(question_tokens.intersection(chunk_tokens)) / max(len(question_tokens), 1)
        vector_score = _cosine(query_vector, chunk.embedding or [])
        score = (settings.rag_lexical_weight * lexical) + (settings.rag_vector_weight * vector_score)
        scored.append(
            RetrievedChunk(
                chunk_id=chunk.id,
                document_id=document.id,
                title=document.title,
                version=document.version,
                owner_department=document.owner_department,
                escalation_contact=document.escalation_contact,
                source_uri=document.source_uri,
                heading_path=chunk.heading_path,
                text=chunk.chunk_text,
                page=chunk.page,
                score=score,
            )
        )
    return sorted(scored, key=lambda item: item.score, reverse=True)[:top_k]
