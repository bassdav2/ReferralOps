from __future__ import annotations

import re
import string

from backend.app.documents.parser_pdf import ParsedDocument
from backend.app.referral.schemas import EvidenceItem


def _normalize(value: str) -> str:
    no_punctuation = value.translate(str.maketrans("", "", string.punctuation))
    return re.sub(r"\s+", " ", no_punctuation.lower()).strip()


def align_to_pages(evidence: list[EvidenceItem], parsed: ParsedDocument) -> list[EvidenceItem]:
    for item in evidence:
        if item.page is not None:
            continue
        quote = _normalize(item.quote)
        if not quote:
            continue
        quote_probe = quote if len(quote) <= 80 else quote[:80]
        for page in parsed.pages:
            page_text = _normalize(page.text)
            if quote_probe in page_text or (len(quote_probe) > 30 and quote_probe[:30] in page_text):
                item.page = page.page_number
                break
    return evidence
