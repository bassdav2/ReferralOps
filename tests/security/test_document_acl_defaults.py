from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.documents.registry import register_file


def test_patient_document_requires_explicit_access_groups(session, tmp_path: Path):
    sample = tmp_path / "patient_referral.txt"
    sample.write_text("Synthetische Zuweisung.", encoding="utf-8")

    with pytest.raises(ValueError):
        register_file(session, sample, contains_patient_data=True, access_groups=None)


def test_patient_document_rejects_all_staff_acl(session, tmp_path: Path):
    sample = tmp_path / "patient_referral.txt"
    sample.write_text("Synthetische Zuweisung.", encoding="utf-8")

    with pytest.raises(ValueError):
        register_file(session, sample, contains_patient_data=True, access_groups=["all_staff"])


def test_patient_document_allows_reviewer_acl(session, tmp_path: Path):
    sample = tmp_path / "patient_referral.txt"
    sample.write_text("Synthetische Zuweisung.", encoding="utf-8")

    document = register_file(
        session,
        sample,
        contains_patient_data=True,
        access_groups=["referral_reviewers"],
    )

    assert document.access_groups == ["referral_reviewers"]


def test_non_patient_document_without_access_groups_fails_closed(session, tmp_path: Path):
    sample = tmp_path / "guideline.txt"
    sample.write_text("Interne Richtlinie ohne Patientendaten.", encoding="utf-8")

    document = register_file(session, sample, contains_patient_data=False, access_groups=None)

    assert document.access_groups == []
