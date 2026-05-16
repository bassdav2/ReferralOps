from __future__ import annotations

from typing import Protocol


class LLMClient(Protocol):
    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> dict: ...

