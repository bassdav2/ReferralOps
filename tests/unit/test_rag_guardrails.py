from __future__ import annotations

from backend.app.rag.guardrails import looks_patient_specific


def test_patient_specific_discharge_question_is_refused():
    assert looks_patient_specific("Soll Patient Max Muster heute entlassen werden?") is True


def test_administrative_policy_question_with_clinical_word_is_allowed():
    assert looks_patient_specific("Wo finde ich die Richtlinie zur Diagnosekodierung?") is False


def test_standalone_clinical_decision_word_is_refused():
    assert looks_patient_specific("Welche Therapie soll ich auswaehlen?") is True
