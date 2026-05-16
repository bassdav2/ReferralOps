from __future__ import annotations

from pydantic import BaseModel


class TextChunk(BaseModel):
    heading_path: list[str]
    text: str
    page: int | None = None
    order_index: int


def chunk_markdown(text: str, *, max_words: int = 180) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    heading_path: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        if buffer:
            chunks.append(
                TextChunk(
                    heading_path=heading_path.copy(),
                    text="\n".join(buffer).strip(),
                    order_index=len(chunks),
                )
            )
            buffer = []

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            flush()
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped.lstrip("#").strip()
            heading_path[:] = heading_path[: max(level - 1, 0)] + [title]
            continue
        buffer.append(line)
        if len(" ".join(buffer).split()) >= max_words:
            flush()
    flush()
    return [chunk for chunk in chunks if chunk.text]

