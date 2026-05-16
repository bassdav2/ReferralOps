from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.core.config import get_settings
from backend.app.main import app
from backend.app.model_gateway import get_embedding_client, get_llm_client
from backend.app.model_gateway.url_safety import assert_local_or_allowed_url


def test_no_external_ai_hosts_or_sdk_imports_in_repo():
    root = Path(__file__).resolve().parents[2]
    forbidden_hosts = [
        "api." + "openai.com",
        "api." + "anthropic.com",
        "generativelanguage." + "googleapis.com",
        "google." + "generativeai",
    ]
    forbidden_imports = [
        re.compile(r"^\s*from\s+openai\s+import\b", re.MULTILINE),
        re.compile(r"^\s*import\s+openai\b", re.MULTILINE),
        re.compile(r"^\s*from\s+anthropic\s+import\b", re.MULTILINE),
        re.compile(r"^\s*import\s+anthropic\b", re.MULTILINE),
    ]
    allowed_suffixes = {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".md",
        ".yml",
        ".yaml",
        ".toml",
        ".env",
        ".example",
    }
    offenders: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in allowed_suffixes:
            continue
        if any(part in {".git", ".venv", "node_modules"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for needle in forbidden_hosts:
            if needle in text:
                offenders.append(f"{path.relative_to(root)} contains {needle}")
        for pattern in forbidden_imports:
            if pattern.search(text):
                offenders.append(f"{path.relative_to(root)} contains external AI SDK import")

    assert offenders == []


@pytest.mark.parametrize(
    "host_url",
    [
        "https://" + "api." + "openai.com/v1",
        "https://" + "generativelanguage." + "googleapis.com/v1",
        "https://" + "anthropic." + "com/v1",
        "https://public-model.example.com/v1",
    ],
)
def test_gemma_vllm_rejects_external_base_url_when_no_external_ai_calls(monkeypatch, host_url: str):
    monkeypatch.setenv("MODEL_PROVIDER", "gemma_vllm")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", host_url)
    monkeypatch.setenv("LOCAL_LLM_ALLOWED_HOSTS", "localhost,127.0.0.1,model-server,host.docker.internal")
    monkeypatch.setenv("NO_EXTERNAL_AI_CALLS", "true")
    get_settings.cache_clear()

    with pytest.raises(HTTPException):
        get_llm_client()


@pytest.mark.parametrize(
    "host_url,allowed",
    [
        ("http://localhost:8080/v1", ["localhost"]),
        ("http://127.0.0.1:8080/v1", ["127.0.0.1"]),
        ("http://model-server:8080/v1", ["model-server"]),
        ("http://host.docker.internal:8080/v1", ["host.docker.internal"]),
    ],
)
def test_gemma_vllm_allows_localhost_and_model_server(host_url: str, allowed: list[str]):
    assert_local_or_allowed_url(host_url, allowed)


def test_health_does_not_ping_external_model_server(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "gemma_vllm")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "https://" + "api." + "openai.com/v1")
    monkeypatch.setenv("LOCAL_LLM_ALLOWED_HOSTS", "localhost")
    monkeypatch.setenv("NO_EXTERNAL_AI_CALLS", "true")
    get_settings.cache_clear()

    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["local_llm_url_allowed"] is False
    assert payload["local_llm_base_url_host"] == "api." + "openai.com"


def test_embeddinggemma_local_requires_local_path(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "embeddinggemma_local")
    monkeypatch.delenv("LOCAL_EMBEDDING_MODEL_PATH", raising=False)
    monkeypatch.setenv("NO_EXTERNAL_AI_CALLS", "true")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="LOCAL_EMBEDDING_MODEL_PATH"):
        get_embedding_client()
