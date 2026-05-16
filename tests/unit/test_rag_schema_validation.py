from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.rag.schemas import GuidelineChatRequest, GuidelineFeedbackRequest


def test_guideline_question_requires_non_empty_text():
    with pytest.raises(ValidationError):
        GuidelineChatRequest(question="")


def test_guideline_feedback_rejects_unknown_label():
    with pytest.raises(ValidationError):
        GuidelineFeedbackRequest(object_id="question-1", label="maybe")


def test_guideline_feedback_accepts_supported_label():
    request = GuidelineFeedbackRequest(object_id="question-1", label="unsafe")

    assert request.label == "unsafe"
