from __future__ import annotations

import re

STOPWORDS = {
    "der",
    "die",
    "das",
    "ich",
    "wie",
    "was",
    "und",
    "oder",
    "ein",
    "eine",
    "einen",
    "ist",
    "im",
    "in",
    "zu",
    "zur",
    "nach",
    "beim",
    "darf",
}


def content_terms(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-ZäöüÄÖÜß0-9]+", text.lower())
        if token not in STOPWORDS and len(token) > 2
    }
