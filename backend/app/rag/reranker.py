from __future__ import annotations

from backend.app.rag.schemas import RetrievedChunk


def filter_relevant(chunks: list[RetrievedChunk], min_score: float = 0.18) -> list[RetrievedChunk]:
    return [chunk for chunk in chunks if chunk.score >= min_score]

