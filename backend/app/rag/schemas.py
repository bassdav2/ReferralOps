from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def _truncate_text(value: Any, max_chars: int) -> Any:
    if isinstance(value, str) and len(value) > max_chars:
        return value[:max_chars].rstrip()
    return value


def _truncate_text_list(value: Any, *, max_items: int, max_chars: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    return [str(_truncate_text(str(item), max_chars)) for item in value[:max_items] if item is not None]


class GuidelineSource(BaseModel):
    document_id: str
    title: str
    version: str
    chunk_id: str
    page: int | None = None
    quote: str

    @field_validator("quote", mode="before")
    @classmethod
    def cap_quote(cls, value: Any) -> Any:
        return _truncate_text(value, 500)


class GuidelineAnswer(BaseModel):
    question_id: str | None = None
    answer: str
    confidence: str
    sources: list[GuidelineSource] = Field(default_factory=list)
    limitations: str | None = None
    escalation_required: bool = False
    escalation_contact: str | None = None
    safety_flags: list[str] = Field(default_factory=list)

    @field_validator("safety_flags", mode="before")
    @classmethod
    def cap_safety_flags(cls, value: Any) -> list[str]:
        return _truncate_text_list(value, max_items=12, max_chars=120)


class GuidelineChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class GuidelineFeedbackRequest(BaseModel):
    object_id: str = Field(min_length=1)
    label: Literal["correct", "unclear", "wrong", "unsafe"]
    comment: str | None = Field(default=None, max_length=1000)


class RetrievedChunk(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    version: str
    owner_department: str
    escalation_contact: str | None = None
    source_uri: str | None = None
    heading_path: list[str]
    text: str
    page: int | None = None
    score: float
