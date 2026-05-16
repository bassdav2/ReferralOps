from __future__ import annotations

# Minimal demo helper, not a production de-identification pipeline.
import re

DATE_RE = re.compile(r"\b\d{1,2}[.]\d{1,2}[.]\d{4}\b")


def redact_for_error_log(text: str) -> str:
    text = DATE_RE.sub("[DATE]", text)
    text = re.sub(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", "[NAME]", text)
    return text
