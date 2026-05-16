from __future__ import annotations

import json

import httpx
import pytest
from fastapi import HTTPException

from backend.app.core.config import get_settings
from backend.app.model_gateway import get_embedding_client, get_llm_client
from backend.app.model_gateway.gemma_vllm_client import (
    GemmaVLLMClient,
    ModelGatewayError,
    httpx_timeout,
    openai_compatible_url,
)
from backend.app.model_gateway.lexical_embedding_client import LexicalOnlyEmbeddingClient
from backend.app.model_gateway.test_double_client import TestDoubleLLMClient
from backend.app.model_gateway.url_safety import assert_local_or_allowed_url


def test_url_safety_blocks_external_host():
    with pytest.raises(HTTPException):
        assert_local_or_allowed_url("https://api.example.com/v1", ["localhost"])


def test_url_safety_allows_model_server():
    assert_local_or_allowed_url("http://model-server:8080/v1", ["model-server"])


def test_url_safety_allows_host_docker_internal():
    assert_local_or_allowed_url("http://host.docker.internal:8080/v1", ["host.docker.internal"])


def test_openai_compatible_url_accepts_base_with_or_without_v1():
    assert (
        openai_compatible_url("http://model-server:8080", "chat/completions")
        == "http://model-server:8080/v1/chat/completions"
    )
    assert (
        openai_compatible_url("http://model-server:8080/v1", "chat/completions")
        == "http://model-server:8080/v1/chat/completions"
    )


def test_zero_vllm_timeout_disables_http_timeout():
    assert httpx_timeout(0) is None


def test_positive_vllm_timeout_uses_httpx_timeout():
    timeout = httpx_timeout(120)

    assert isinstance(timeout, httpx.Timeout)


def test_get_llm_client_returns_test_double_when_configured(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "test_double")
    get_settings.cache_clear()

    assert isinstance(get_llm_client(), TestDoubleLLMClient)


def test_get_embedding_client_returns_lexical_only_provider(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "lexical_only")
    get_settings.cache_clear()

    assert isinstance(get_embedding_client(), LexicalOnlyEmbeddingClient)


def test_get_llm_client_returns_vllm_for_local_provider(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "gemma_vllm")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://localhost:8080")
    monkeypatch.setenv("LOCAL_LLM_ALLOWED_HOSTS", "localhost")
    monkeypatch.setenv("NO_EXTERNAL_AI_CALLS", "true")
    get_settings.cache_clear()

    assert isinstance(get_llm_client(), GemmaVLLMClient)


def test_get_llm_client_rejects_external_provider_url(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "gemma_vllm")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "https://api.external.example/v1")
    monkeypatch.setenv("LOCAL_LLM_ALLOWED_HOSTS", "localhost")
    monkeypatch.setenv("NO_EXTERNAL_AI_CALLS", "true")
    get_settings.cache_clear()

    with pytest.raises(HTTPException):
        get_llm_client()


def run_vllm_client_parses_json_scenario(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"ok": true, "value": "demo"}'}},
                ],
            },
        )

    transport = httpx.MockTransport(handler)

    class MockClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=transport)

    monkeypatch.setattr(httpx, "Client", MockClient)

    client = GemmaVLLMClient(
        base_url="http://model-server:8080/v1",
        model_id="gemma-local",
        allowed_hosts=["model-server"],
    )
    result = client.generate_json(
        system_prompt="system",
        user_prompt="user",
        schema={"type": "object"},
    )
    assert result == {"ok": True, "value": "demo"}


def test_vllm_client_parses_json(monkeypatch):
    run_vllm_client_parses_json_scenario(monkeypatch)


def test_vllm_client_sends_openai_compatible_chat_completion(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json_payload = request.read()
        assert b'"model":"gemma-local"' in json_payload
        assert b'"temperature":0.0' in json_payload
        assert b'"max_tokens":128' in json_payload
        assert b'"messages"' in json_payload
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok": true}'}}]},
        )

    transport = httpx.MockTransport(handler)

    class MockClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=transport)

    monkeypatch.setattr(httpx, "Client", MockClient)
    client = GemmaVLLMClient(
        base_url="http://model-server:8080",
        model_id="gemma-local",
        allowed_hosts=["model-server"],
    )

    assert client.generate_json(system_prompt="system", user_prompt="user", schema={}, max_tokens=128) == {"ok": True}
    assert captured["url"] == "http://model-server:8080/v1/chat/completions"


def test_vllm_client_prefers_json_schema_and_falls_back_to_json_object(monkeypatch):
    response_formats: list[dict | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        response_formats.append(payload.get("response_format"))
        if payload.get("response_format", {}).get("type") == "json_schema":
            return httpx.Response(400, json={"error": "'response_format.type' must be 'json_object' or 'text'"})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok": true}'}}]},
        )

    transport = httpx.MockTransport(handler)

    class MockClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=transport)

    monkeypatch.setattr(httpx, "Client", MockClient)
    client = GemmaVLLMClient(
        base_url="http://model-server:8080",
        model_id="gemma-local",
        allowed_hosts=["model-server"],
    )

    assert client.generate_json(system_prompt="system", user_prompt="user", schema={"type": "object"}) == {"ok": True}
    assert response_formats[0]["type"] == "json_schema"
    assert response_formats[1] == {"type": "json_object"}


def test_vllm_client_parses_json_content(monkeypatch):
    run_vllm_client_parses_json_scenario(monkeypatch)


def test_vllm_client_repairs_json_surrounded_by_text(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "```json\n{\"ok\": true, \"value\": \"demo\"}\n```"}},
                ],
            },
        )

    transport = httpx.MockTransport(handler)

    class MockClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=transport)

    monkeypatch.setattr(httpx, "Client", MockClient)

    client = GemmaVLLMClient(
        base_url="http://model-server:8080/v1",
        model_id="gemma-local",
        allowed_hosts=["model-server"],
    )

    result = client.generate_json(
        system_prompt="system",
        user_prompt="user",
        schema={"type": "object"},
    )
    assert result == {"ok": True, "value": "demo"}


def run_vllm_client_retries_with_repair_prompt_after_unparseable_json_scenario(monkeypatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        content = "not json at all" if calls == 1 else '{"ok": true, "value": "repaired"}'
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": content}},
                ],
            },
        )

    transport = httpx.MockTransport(handler)

    class MockClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=transport)

    monkeypatch.setattr(httpx, "Client", MockClient)

    client = GemmaVLLMClient(
        base_url="http://model-server:8080",
        model_id="gemma-local",
        allowed_hosts=["model-server"],
    )

    result = client.generate_json(
        system_prompt="system",
        user_prompt="user",
        schema={"type": "object"},
    )
    assert result == {"ok": True, "value": "repaired"}
    assert calls == 2


def test_vllm_client_retries_with_repair_prompt_after_unparseable_json(monkeypatch):
    run_vllm_client_retries_with_repair_prompt_after_unparseable_json_scenario(monkeypatch)


def test_vllm_client_handles_malformed_json_without_raw_crash(monkeypatch):
    run_vllm_client_retries_with_repair_prompt_after_unparseable_json_scenario(monkeypatch)


def test_vllm_client_reports_unexpected_response_shape(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    transport = httpx.MockTransport(handler)

    class MockClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=transport)

    monkeypatch.setattr(httpx, "Client", MockClient)

    client = GemmaVLLMClient(
        base_url="http://model-server:8080",
        model_id="gemma-local",
        allowed_hosts=["model-server"],
    )

    with pytest.raises(ModelGatewayError, match="unexpected response shape"):
        client.generate_json(system_prompt="system", user_prompt="user", schema={"type": "object"})
