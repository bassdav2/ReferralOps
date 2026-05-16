from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.app.core.config import get_settings
from backend.app.core.errors import bad_request
from backend.app.core.runtime_model_config import (
    LocalModelConfig,
    effective_model_config,
    read_local_model_config,
    validate_local_model_url,
    write_local_model_config,
)
from backend.app.model_gateway.gemma_vllm_client import GemmaVLLMClient
from backend.app.security.acl import require_admin_or_it, require_referral_reviewer
from backend.app.security.auth import DemoUser, get_current_user

router = APIRouter(prefix="/api/runtime", tags=["runtime"])


class LocalModelConfigRead(BaseModel):
    base_url: str | None
    model_id: str | None
    api_key_configured: bool
    timeout_seconds: float | None
    configured: bool


class LocalModelConfigWrite(BaseModel):
    base_url: str
    model_id: str
    api_key: str | None = None
    timeout_seconds: float | None = Field(default=0, ge=0)


def _read_payload(config: LocalModelConfig) -> LocalModelConfigRead:
    return LocalModelConfigRead(
        base_url=config.base_url or None,
        model_id=config.model_id or None,
        api_key_configured=bool(get_settings().local_llm_api_key),
        timeout_seconds=config.timeout_seconds,
        configured=config.configured,
    )


@router.get("/model-config", response_model=LocalModelConfigRead)
def get_model_config(user: DemoUser = Depends(get_current_user)) -> LocalModelConfigRead:
    require_admin_or_it(user)
    return _read_payload(read_local_model_config())


@router.post("/model-config", response_model=LocalModelConfigRead)
def save_model_config(
    request: LocalModelConfigWrite,
    user: DemoUser = Depends(get_current_user),
) -> LocalModelConfigRead:
    require_admin_or_it(user)
    if not request.model_id.strip():
        raise bad_request("Model ID is required.")
    normalized = validate_local_model_url(request.base_url)
    saved = write_local_model_config(
        LocalModelConfig(
            base_url=normalized,
            model_id=request.model_id.strip(),
            api_key=None,
            timeout_seconds=request.timeout_seconds,
        )
    )
    return _read_payload(saved)


@router.post("/model-smoke-test")
def smoke_test_model(user: DemoUser = Depends(get_current_user)) -> dict:
    require_referral_reviewer(user)
    config = effective_model_config()
    if config.provider != "gemma_vllm":
        return {"status": "failed", "message": "No local OpenAI-compatible model is configured."}
    try:
        result = GemmaVLLMClient(
            base_url=config.base_url,
            model_id=config.model_id,
            api_key=config.api_key,
            timeout_seconds=config.timeout_seconds,
            allowed_hosts=config.allowed_hosts,
        ).generate_json(
            system_prompt="Return only valid JSON.",
            user_prompt="Return a JSON object with ok=true and mode='local'.",
            schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "mode": {"type": "string"},
                },
                "required": ["ok"],
            },
            temperature=0.0,
            max_tokens=64,
        )
    except Exception as exc:
        return {"status": "failed", "message": str(exc)}
    return {
        "status": "connected",
        "model_id": config.model_id,
        "base_url": config.base_url,
        "result": result,
    }
