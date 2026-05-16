from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import httpx

from backend.app.model_gateway.json_repair import parse_or_repair_json
from backend.app.model_gateway.url_safety import assert_local_or_allowed_url


class ModelGatewayError(RuntimeError):
    pass


def httpx_timeout(timeout_seconds: float) -> httpx.Timeout | None:
    if timeout_seconds <= 0:
        return None
    return httpx.Timeout(timeout_seconds)


def openai_compatible_url(base_url: str, path: str) -> str:
    stripped = base_url.rstrip("/")
    parsed = urlparse(stripped)
    if parsed.path.rstrip("/").endswith("/v1"):
        return f"{stripped}/{path.lstrip('/')}"
    return f"{stripped}/v1/{path.lstrip('/')}"


class GemmaVLLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        model_id: str,
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
        allowed_hosts: list[str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_id = model_id
        self.api_key = api_key or "local-demo"
        self.timeout_seconds = timeout_seconds
        if allowed_hosts is not None:
            assert_local_or_allowed_url(self.base_url, allowed_hosts)

    def _post_chat_completion(
        self,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        json_schema_response_format: dict[str, Any] | None = None,
    ) -> str:
        url = openai_compatible_url(self.base_url, "chat/completions")
        with httpx.Client(timeout=httpx_timeout(self.timeout_seconds)) as client:
            response = client.post(url, headers=headers, json=payload)

            if response.status_code in {400, 422} and "response_format" in payload:
                if payload["response_format"].get("type") == "json_schema":
                    object_payload = dict(payload)
                    object_payload["response_format"] = {"type": "json_object"}
                    response = client.post(url, headers=headers, json=object_payload)

                elif (
                    payload["response_format"].get("type") == "json_object"
                    and json_schema_response_format is not None
                ):
                    schema_payload = dict(payload)
                    schema_payload["response_format"] = json_schema_response_format
                    response = client.post(url, headers=headers, json=schema_payload)

                if response.status_code in {400, 422}:
                    no_format_payload = dict(payload)
                    no_format_payload.pop("response_format", None)
                    response = client.post(url, headers=headers, json=no_format_payload)

            response.raise_for_status()
            data = response.json()

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelGatewayError("Local model server returned an unexpected response shape") from exc

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        "Antworte ausschliesslich als valides JSON. "
                        "Das JSON muss zum folgenden Schema passen:\n"
                        f"{json.dumps(schema, ensure_ascii=False)}\n\n"
                        f"Aufgabe:\n{user_prompt}"
                    ),
                },
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        json_schema_response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "Response",
                "schema": schema,
            },
        }
        payload["response_format"] = json_schema_response_format

        content = self._post_chat_completion(
            headers=headers,
            payload=payload,
            json_schema_response_format=json_schema_response_format,
        )
        try:
            return parse_or_repair_json(content)
        except Exception:
            repair_payload = dict(payload)
            repair_payload["messages"] = [
                {
                    "role": "system",
                    "content": "Du reparierst Modellantworten zu strikt validem JSON ohne Zusatztext.",
                },
                {
                    "role": "user",
                    "content": (
                        "Repariere die folgende Antwort zu einem validen JSON-Objekt, "
                        "das zum Schema passt. Gib ausschliesslich JSON zurueck.\n\n"
                        f"Schema:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
                        f"Antwort:\n{content}"
                    ),
                },
            ]
            repair_payload["temperature"] = 0.0
            repaired_content = self._post_chat_completion(
                headers=headers,
                payload=repair_payload,
                json_schema_response_format=json_schema_response_format,
            )
            return parse_or_repair_json(repaired_content)
