from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from pydantic import BaseModel


class AuditPayload(BaseModel):
    action: str
    object_type: str
    object_id: str
    payload_json: dict[str, Any] | None = None
    model_profile: str | None = None
    prompt_version: str | None = None
    input_hash: str | None = None
    output_hash: str | None = None
    decision_before: dict[str, Any] | None = None
    decision_after: dict[str, Any] | None = None


def hash_json(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def new_id() -> str:
    return uuid.uuid4().hex

