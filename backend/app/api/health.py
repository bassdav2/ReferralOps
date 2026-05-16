from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter

from backend.app.core.config import get_settings
from backend.app.core.runtime_model_config import effective_model_config
from backend.app.db.session import ping_db
from backend.app.model_gateway.url_safety import assert_local_or_allowed_url

router = APIRouter(prefix="/api/health", tags=["health"])


def _local_llm_url_safety_status() -> tuple[bool | None, str | None]:
    settings = get_settings()
    generation = effective_model_config(settings)
    if generation.provider != "gemma_vllm":
        return None, None

    host = urlparse(generation.base_url).hostname
    if settings.no_external_ai_calls:
        try:
            assert_local_or_allowed_url(generation.base_url, generation.allowed_hosts)
        except Exception:
            return False, host

    return None, host


@router.get("")
def health() -> dict:
    settings = get_settings()
    generation = effective_model_config(settings)
    db_ok = False
    try:
        db_ok = ping_db()
    except Exception:
        db_ok = False
    local_llm_url_allowed, local_llm_host = _local_llm_url_safety_status()
    payload = {
        "status": "ok" if db_ok else "degraded",
        "db": "ok" if db_ok else "unavailable",
        "queue": "demo",
        "model_gateway": generation.provider,
        "generation_model_id": generation.model_id,
        "embedding_model_id": settings.embedding_model_id,
        "no_external_ai_calls": settings.no_external_ai_calls,
        "writeback_enabled": settings.writeback_enabled,
        "runtime_model_configured": generation.configured_from_local_file,
    }
    if generation.provider == "gemma_vllm":
        payload["local_llm_url_allowed"] = local_llm_url_allowed
        payload["local_llm_base_url_host"] = local_llm_host
    return payload
