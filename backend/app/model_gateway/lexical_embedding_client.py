from __future__ import annotations

import hashlib
import math
import re

from backend.app.model_gateway.embedding_client import EmbeddingClient


class LexicalOnlyEmbeddingClient(EmbeddingClient):
    """Small deterministic local vectorizer for lexical-first retrieval.

    This keeps the embedding interface available without requiring a model download.
    With RAG_VECTOR_WEIGHT=0.0, retrieval is driven by lexical scoring; these vectors
    are only a compatibility fallback for code paths that expect an embedding.
    """

    dimensions = 48

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in re.findall(r"[a-zA-ZäöüÄÖÜß0-9]+", text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = digest[0] % self.dimensions
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]
