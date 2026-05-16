from __future__ import annotations

from backend.app.rag.guardrails import no_answer
from backend.app.rag.schemas import GuidelineAnswer, GuidelineSource, RetrievedChunk


def source_from_chunk(chunk: RetrievedChunk) -> GuidelineSource:
    quote = " ".join(chunk.text.split())[:280]
    return GuidelineSource(
        document_id=chunk.document_id,
        title=chunk.title,
        version=chunk.version,
        chunk_id=chunk.chunk_id,
        page=chunk.page,
        quote=quote,
    )


def validate_answer_sources(answer: GuidelineAnswer, retrieved: list[RetrievedChunk]) -> GuidelineAnswer:
    by_id = {chunk.chunk_id: chunk for chunk in retrieved}
    normalized = []
    for source in answer.sources:
        chunk = by_id.get(source.chunk_id)
        if chunk:
            normalized.append(source_from_chunk(chunk))
    answer.sources = normalized

    if answer.confidence != "no_answer" and not answer.sources:
        blocked = no_answer("Die Antwort konnte nicht auf freigegebene lokale Quellen zurückgeführt werden.")
        if "ungrounded_answer_blocked" not in blocked.safety_flags:
            blocked.safety_flags.append("ungrounded_answer_blocked")
        return blocked

    return answer
