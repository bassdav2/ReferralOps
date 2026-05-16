from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.app.core.config import get_settings
from backend.app.core.runtime_model_config import (
    LocalModelConfig,
    effective_model_config,
    read_local_model_config,
    validate_local_model_url,
    write_local_model_config,
)


def test_runtime_model_config_persists_private_lan_host(tmp_path, monkeypatch, reset_runtime_caches):
    monkeypatch.setenv("LOCAL_MODEL_CONFIG_PATH", str(tmp_path / "local_model_config.json"))
    monkeypatch.delenv("LOCAL_LLM_API_KEY", raising=False)
    reset_runtime_caches()
    settings = get_settings()

    saved = write_local_model_config(
        LocalModelConfig(
            base_url="http://192.168.1.50:1234/v1",
            model_id="google/gemma-4-31B-it",
            api_key="local-demo",
            timeout_seconds=1,
        ),
        settings,
    )
    loaded = read_local_model_config(settings)
    effective = effective_model_config(settings)

    assert saved.configured is True
    assert saved.api_key is None
    assert loaded.base_url == "http://192.168.1.50:1234/v1"
    assert loaded.model_id == "google/gemma-4-31B-it"
    assert loaded.api_key is None
    assert effective.provider == "gemma_vllm"
    assert effective.base_url == loaded.base_url
    assert effective.api_key == settings.local_llm_api_key
    assert "192.168.1.50" in effective.allowed_hosts


def test_runtime_model_config_defaults_timeout_to_zero(tmp_path, monkeypatch, reset_runtime_caches):
    monkeypatch.setenv("HOSPITAL_AI_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_MODEL_CONFIG_PATH", str(tmp_path / "local_model_config.json"))
    monkeypatch.delenv("LOCAL_LLM_TIMEOUT_SECONDS", raising=False)
    reset_runtime_caches()
    settings = get_settings()

    assert read_local_model_config(settings).timeout_seconds == 0
    assert effective_model_config(settings).timeout_seconds == 0


def test_runtime_model_config_allows_zero_timeout(tmp_path, monkeypatch, reset_runtime_caches):
    monkeypatch.setenv("LOCAL_MODEL_CONFIG_PATH", str(tmp_path / "local_model_config.json"))
    reset_runtime_caches()
    settings = get_settings()

    saved = write_local_model_config(
        LocalModelConfig(
            base_url="http://localhost:1234/v1",
            model_id="google/gemma-4-31B-it",
            timeout_seconds=0,
        ),
        settings,
    )

    assert saved.timeout_seconds == 0
    assert effective_model_config(settings).timeout_seconds == 0


def test_runtime_model_config_rejects_negative_timeout():
    with pytest.raises(ValueError):
        LocalModelConfig(timeout_seconds=-1)


def test_runtime_model_config_rejects_public_host():
    with pytest.raises(HTTPException):
        validate_local_model_url("https://api.external.example/v1")


def test_runtime_model_config_allows_localhost_and_local_dns():
    assert validate_local_model_url("http://localhost:1234/v1") == "http://localhost:1234/v1"
    assert validate_local_model_url("http://gemma.local:1234/v1") == "http://gemma.local:1234/v1"
