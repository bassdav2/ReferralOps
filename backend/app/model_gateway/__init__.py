from __future__ import annotations

from backend.app.core.config import get_settings
from backend.app.core.runtime_model_config import effective_model_config
from backend.app.model_gateway.embedding_client import EmbeddingClient
from backend.app.model_gateway.embeddinggemma_client import EmbeddingGemmaClient
from backend.app.model_gateway.gemma_vllm_client import GemmaVLLMClient
from backend.app.model_gateway.lexical_embedding_client import LexicalOnlyEmbeddingClient
from backend.app.model_gateway.llm_client import LLMClient
from backend.app.model_gateway.test_double_client import TestDoubleEmbeddingClient, TestDoubleLLMClient


def get_llm_client() -> LLMClient:
    settings = get_settings()
    generation = effective_model_config(settings)

    if generation.provider == "gemma_vllm":
        return GemmaVLLMClient(
            base_url=generation.base_url,
            model_id=generation.model_id,
            api_key=generation.api_key,
            timeout_seconds=generation.timeout_seconds,
            allowed_hosts=generation.allowed_hosts if settings.no_external_ai_calls else None,
        )

    if generation.provider == "test_double":
        return TestDoubleLLMClient()

    raise ValueError(f"Unsupported MODEL_PROVIDER: {generation.provider}")


def get_embedding_client() -> EmbeddingClient:
    settings = get_settings()

    if settings.embedding_provider == "lexical_only":
        return LexicalOnlyEmbeddingClient()

    if settings.embedding_provider == "embeddinggemma_local":
        if settings.no_external_ai_calls and not settings.local_embedding_model_path:
            raise ValueError(
                "LOCAL_EMBEDDING_MODEL_PATH is required for embeddinggemma_local when NO_EXTERNAL_AI_CALLS=true"
            )
        return EmbeddingGemmaClient(
            model_id=settings.local_embedding_model_path or settings.embedding_model_id,
            local_files_only=True if settings.no_external_ai_calls else settings.embedding_local_files_only,
        )

    if settings.embedding_provider == "test_double":
        return TestDoubleEmbeddingClient()

    raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {settings.embedding_provider}")
