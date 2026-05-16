from __future__ import annotations

from pydantic import ValidationError

from backend.app.rag.guardrails import no_answer
from backend.app.rag.schemas import GuidelineAnswer


def validate_guideline_payload(payload: dict) -> GuidelineAnswer:
    try:
        return GuidelineAnswer.model_validate(payload)
    except ValidationError:
        answer = no_answer("Model response did not validate against GuidelineAnswer schema.")
        if "invalid_model_schema" not in answer.safety_flags:
            answer.safety_flags.append("invalid_model_schema")
        return answer
