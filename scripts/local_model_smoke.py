from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    if os.getenv("RUN_REAL_LOCAL_MODEL_SMOKE") != "1":
        raise SystemExit("Set RUN_REAL_LOCAL_MODEL_SMOKE=1 to run the real local model smoke test")

    from backend.app.core.config import get_settings
    from backend.app.model_gateway import get_llm_client
    from backend.app.model_gateway.gemma_vllm_client import ModelGatewayError

    settings = get_settings()
    if settings.model_provider != "gemma_vllm":
        raise SystemExit("MODEL_PROVIDER must be gemma_vllm for this smoke test")
    if not settings.no_external_ai_calls:
        raise SystemExit("NO_EXTERNAL_AI_CALLS must be true")

    try:
        result = get_llm_client().generate_json(
            system_prompt="Return only valid JSON.",
            user_prompt='Return {"ok": true, "mode": "local"}.',
            schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "mode": {"type": "string"},
                },
                "required": ["ok"],
            },
            temperature=0.0,
            max_tokens=settings.generation_max_tokens,
        )
    except ModelGatewayError as exc:
        raise SystemExit(f"Local model smoke failed: {exc}") from exc
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise SystemExit(f"Unexpected local model response: {result}")
    print(json.dumps({"status": "ok", "result": result}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
