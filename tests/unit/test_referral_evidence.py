from __future__ import annotations

from backend.app.documents.parser_pdf import ParsedDocument, ParsedPage
from backend.app.referral.evidence import align_to_pages
from backend.app.referral.schemas import EvidenceItem


def test_evidence_alignment_normalizes_whitespace_case_and_punctuation():
    parsed = ParsedDocument(
        pages=[ParsedPage(page_number=3, text="Zuweisung wegen Thoraxbeschwerden und Dyspnoe.")]
    )
    evidence = [EvidenceItem(claim="symptom", quote="thoraxbeschwerden   UND dyspnoe")]

    aligned = align_to_pages(evidence, parsed)

    assert aligned[0].page == 3
