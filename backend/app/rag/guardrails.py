from __future__ import annotations

import re

from backend.app.rag.constants import CONFIDENCE_NO_ANSWER
from backend.app.rag.schemas import GuidelineAnswer

PATIENT_ANCHOR_PATTERNS = [
    r"\bpatient(in)?\b",
    r"\bmax muster\b",
]

CLINICAL_DECISION_PATTERNS = [
    r"\bentlassen\b",
    r"\bdiagnose\b",
    r"\btherapie\b",
    r"\bbehandlung\b",
    r"\bmedikation fuer\b",
    r"\bpriorisierung\b",
]

ADMINISTRATIVE_POLICY_PATTERNS = [
    r"\brichtlinie\b",
    r"\bprozess\b",
    r"\badministrativ\b",
    r"\bantrag\b",
    r"\bzugang\b",
    r"\bkodierung\b",
]


def looks_patient_specific(question: str) -> bool:
    lowered = question.lower()
    has_patient_anchor = any(re.search(pattern, lowered) for pattern in PATIENT_ANCHOR_PATTERNS)
    has_clinical_decision = any(re.search(pattern, lowered) for pattern in CLINICAL_DECISION_PATTERNS)
    has_administrative_policy = any(re.search(pattern, lowered) for pattern in ADMINISTRATIVE_POLICY_PATTERNS)

    if has_patient_anchor:
        return True
    if has_clinical_decision and has_administrative_policy:
        return False
    return has_clinical_decision


def refusal_patient_specific() -> GuidelineAnswer:
    return GuidelineAnswer(
        answer="Ich finde dazu in den verfuegbaren internen Quellen keine verlaessliche Antwort.",
        confidence=CONFIDENCE_NO_ANSWER,
        sources=[],
        limitations="Patientenspezifische oder klinische Entscheidungen sind nicht Teil dieses Assistenten.",
        escalation_required=True,
        escalation_contact=None,
        safety_flags=["patient_specific_or_clinical"],
    )


def no_answer(reason: str = "Keine ausreichende lokale Quelle.") -> GuidelineAnswer:
    return GuidelineAnswer(
        answer="Ich finde dazu in den verfuegbaren internen Quellen keine verlaessliche Antwort.",
        confidence=CONFIDENCE_NO_ANSWER,
        sources=[],
        limitations=reason,
        escalation_required=True,
        escalation_contact=None,
        safety_flags=["no_answer"],
    )
