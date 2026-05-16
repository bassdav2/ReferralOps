from __future__ import annotations

from backend.app.model_gateway.embedding_client import EmbeddingClient


class EmbeddingGemmaClient(EmbeddingClient):
    def __init__(
        self,
        model_id: str = "google/embeddinggemma-300m",
        local_files_only: bool = False,
    ) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_id = model_id
        self.model = SentenceTransformer(model_id, local_files_only=local_files_only)

    def embed_query(self, text: str) -> list[float]:
        return self.model.encode(text, normalize_embeddings=True).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True).tolist()
