from __future__ import annotations

from urllib.parse import urlparse

from backend.app.core.errors import bad_request


def assert_local_or_allowed_url(base_url: str, allowed_hosts: list[str]) -> None:
    parsed = urlparse(base_url)
    host = parsed.hostname

    if parsed.scheme not in {"http", "https"}:
        raise bad_request("LOCAL_LLM_BASE_URL must use http or https")

    if not host:
        raise bad_request("LOCAL_LLM_BASE_URL must include a host")

    if host not in set(allowed_hosts):
        raise bad_request(
            f"External model endpoint blocked by local-only policy: {host}. "
            "Add it to LOCAL_LLM_ALLOWED_HOSTS only for internal endpoints."
        )


def assert_local_model_url_allowed(base_url: str, allowed_hosts: list[str]) -> None:
    assert_local_or_allowed_url(base_url, allowed_hosts)
