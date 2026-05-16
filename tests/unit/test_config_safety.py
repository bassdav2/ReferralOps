from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.app.core.config import get_settings
from backend.app.security.auth import get_current_user


def test_invalid_integer_env_var_reports_variable_name(monkeypatch):
    monkeypatch.setenv("GENERATION_MAX_TOKENS", "many")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="GENERATION_MAX_TOKENS"):
        get_settings()


def test_local_model_timeout_allows_zero(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_TIMEOUT_SECONDS", "0")
    get_settings.cache_clear()

    assert get_settings().local_llm_timeout_seconds == 0


def test_local_model_timeout_rejects_negative(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_TIMEOUT_SECONDS", "-1")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="LOCAL_LLM_TIMEOUT_SECONDS"):
        get_settings()


def test_default_cors_allows_localhost_and_ipv4_loopback(monkeypatch):
    monkeypatch.delenv("BACKEND_CORS_ORIGINS", raising=False)
    get_settings.cache_clear()

    origins = get_settings().cors_origins

    assert "http://localhost:5173" in origins
    assert "http://127.0.0.1:5173" in origins


def test_non_demo_auth_mode_fails_closed(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "oidc")
    get_settings.cache_clear()

    with pytest.raises(HTTPException):
        get_current_user("sekretariat_kardiologie")
