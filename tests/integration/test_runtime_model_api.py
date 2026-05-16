from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient

from backend.app.core.config import get_settings
from backend.app.core.runtime_model_config import effective_model_config


def test_model_smoke_endpoint_reports_failure_without_config():
    from backend.app.main import app

    response = TestClient(app).post(
        "/api/runtime/model-smoke-test",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"


def test_model_config_and_smoke_endpoint_success(monkeypatch):
    from backend.app.main import app

    client = TestClient(app)
    response = client.post(
        "/api/runtime/model-config",
        headers={"X-Demo-User": "it_admin"},
        json={
            "base_url": "http://localhost:1234/v1",
            "model_id": "google/gemma-4-31B-it",
            "api_key": "must-not-persist",
            "timeout_seconds": 0,
        },
    )
    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert response.json()["timeout_seconds"] == 0
    saved_payload = json.loads(get_settings().local_model_config_path.read_text(encoding="utf-8"))
    assert "api_key" not in saved_payload

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true, "mode": "local"}'}}]})

    transport = httpx.MockTransport(handler)

    class MockClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=transport)

    monkeypatch.setattr(httpx, "Client", MockClient)

    smoke = client.post(
        "/api/runtime/model-smoke-test",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
    )

    assert smoke.status_code == 200
    assert smoke.json()["status"] == "connected"


def test_model_config_write_requires_admin_or_it():
    from backend.app.main import app

    response = TestClient(app).post(
        "/api/runtime/model-config",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
        json={"base_url": "http://localhost:1234/v1", "model_id": "google/gemma-4-31B-it", "timeout_seconds": 0},
    )

    assert response.status_code == 403


def test_model_config_write_rejects_negative_timeout():
    from backend.app.main import app

    response = TestClient(app).post(
        "/api/runtime/model-config",
        headers={"X-Demo-User": "it_admin"},
        json={"base_url": "http://localhost:1234/v1", "model_id": "google/gemma-4-31B-it", "timeout_seconds": -1},
    )

    assert response.status_code == 422


def test_runtime_model_config_uses_environment_api_key(monkeypatch):
    from backend.app.main import app

    client = TestClient(app)
    response = client.post(
        "/api/runtime/model-config",
        headers={"X-Demo-User": "it_admin"},
        json={"base_url": "http://localhost:1234/v1", "model_id": "google/gemma-4-31B-it", "timeout_seconds": 0},
    )
    assert response.status_code == 200

    monkeypatch.setenv("LOCAL_LLM_API_KEY", "env-secret")
    get_settings.cache_clear()

    assert effective_model_config().api_key == "env-secret"
