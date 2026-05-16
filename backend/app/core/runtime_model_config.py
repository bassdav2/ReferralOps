from __future__ import annotations

import json
import logging
from ipaddress import ip_address
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from backend.app.core.config import Settings, get_settings
from backend.app.core.errors import bad_request

logger = logging.getLogger(__name__)


class LocalModelConfig(BaseModel):
    base_url: str = ""
    model_id: str = ""
    api_key: str | None = None
    timeout_seconds: float | None = Field(default=0, ge=0)

    @property
    def configured(self) -> bool:
        return bool(self.base_url.strip() and self.model_id.strip())


class EffectiveModelConfig(BaseModel):
    provider: str
    base_url: str
    model_id: str
    api_key: str | None
    timeout_seconds: float
    allowed_hosts: list[str]
    configured_from_local_file: bool


def _is_private_or_local_host(host: str) -> bool:
    lowered = host.lower()
    if lowered in {"localhost", "127.0.0.1", "::1", "host.docker.internal", "model-server"}:
        return True
    if lowered.endswith(".local"):
        return True
    try:
        parsed = ip_address(lowered)
    except ValueError:
        return False
    return parsed.is_private or parsed.is_loopback or parsed.is_link_local


def validate_local_model_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"}:
        raise bad_request("Local model URL must start with http:// or https://")
    if not parsed.hostname:
        raise bad_request("Local model URL must include a host")
    if not _is_private_or_local_host(parsed.hostname):
        raise bad_request("Only localhost, .local, or private LAN model hosts are allowed")
    return normalized


def read_local_model_config(settings: Settings | None = None) -> LocalModelConfig:
    settings = settings or get_settings()
    path = settings.local_model_config_path
    if not path.exists():
        return LocalModelConfig()
    try:
        config = LocalModelConfig.model_validate_json(path.read_text(encoding="utf-8"))
        return config.model_copy(update={"api_key": None})
    except Exception as exc:
        logger.warning("Could not read local model config from %s: %s", path, exc)
        return LocalModelConfig()


def write_local_model_config(config: LocalModelConfig, settings: Settings | None = None) -> LocalModelConfig:
    settings = settings or get_settings()
    config = config.model_copy(update={"api_key": None})
    if config.base_url.strip():
        config.base_url = validate_local_model_url(config.base_url)
    if config.model_id.strip():
        config.model_id = config.model_id.strip()
    settings.local_model_config_path.write_text(
        json.dumps(config.model_dump(exclude={"api_key"}), ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return config


def effective_model_config(settings: Settings | None = None) -> EffectiveModelConfig:
    settings = settings or get_settings()
    local = read_local_model_config(settings)
    if local.configured:
        host = urlparse(local.base_url).hostname
        configured_hosts = [*settings.local_llm_allowed_hosts, host] if host else settings.local_llm_allowed_hosts
        allowed_hosts = list(dict.fromkeys(configured_hosts))
        return EffectiveModelConfig(
            provider="gemma_vllm",
            base_url=local.base_url,
            model_id=local.model_id,
            api_key=settings.local_llm_api_key,
            timeout_seconds=local.timeout_seconds
            if local.timeout_seconds is not None
            else settings.local_llm_timeout_seconds,
            allowed_hosts=allowed_hosts,
            configured_from_local_file=True,
        )
    return EffectiveModelConfig(
        provider=settings.model_provider,
        base_url=settings.local_llm_base_url,
        model_id=settings.generation_model_id,
        api_key=settings.local_llm_api_key,
        timeout_seconds=settings.local_llm_timeout_seconds,
        allowed_hosts=settings.local_llm_allowed_hosts,
        configured_from_local_file=False,
    )
