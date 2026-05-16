from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.app.db.models import Document
from backend.app.documents.registry import get_visible_document, register_file
from backend.app.rag.ingest import ingest_guideline_sources
from backend.app.referral.ingest import ingest_referral_sources
from backend.app.security.auth import get_current_user


def test_empty_access_groups_are_not_visible_to_any_demo_user(session):
    document = Document(
        id="empty-acl-doc",
        source_system="test",
        external_id="empty-acl",
        title="Empty ACL",
        mime_type="text/plain",
        sha256="0" * 64,
        storage_pointer="missing",
        source_uri="missing",
        access_groups=[],
        contains_patient_data=False,
        parse_status="parsed",
    )
    session.add(document)
    session.commit()

    for username in ["sekretariat_kardiologie", "it_admin", "hygiene_user", "restricted_user"]:
        with pytest.raises(HTTPException):
            get_visible_document(session, document.id, get_current_user(username))


def test_patient_document_without_access_groups_is_rejected_or_referral_reviewers_only(session, tmp_path: Path):
    sample = tmp_path / "patient_without_acl.txt"
    sample.write_text("Synthetische Zuweisung.", encoding="utf-8")

    with pytest.raises(ValueError):
        register_file(session, sample, contains_patient_data=True, access_groups=None)

    document = register_file(
        session,
        sample,
        contains_patient_data=True,
        access_groups=["referral_reviewers"],
    )
    assert document.access_groups == ["referral_reviewers"]


def test_referral_source_missing_access_groups_fails_validation(
    monkeypatch, reset_runtime_caches, session, tmp_path: Path
):
    root = tmp_path
    docs = root / "referrals"
    configs = root / "configs"
    docs.mkdir()
    configs.mkdir()
    (docs / "referral.txt").write_text("Zuweisung wegen Thoraxbeschwerden.", encoding="utf-8")
    (configs / "referral_sources.yml").write_text(
        """
sources:
  missing_acl:
    adapter: filesystem
    path: referrals
    contains_patient_data: true
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("HOSPITAL_AI_ROOT", str(root))
    reset_runtime_caches()

    with pytest.raises(ValueError, match="requires explicit access_groups"):
        ingest_referral_sources(session)


def test_guideline_source_missing_access_groups_fails_validation(
    monkeypatch, reset_runtime_caches, session, tmp_path: Path
):
    root = tmp_path
    docs = root / "guidelines"
    configs = root / "configs"
    docs.mkdir()
    configs.mkdir()
    (docs / "policy.md").write_text("# Policy\n\nKIS-Zugang beantragen.", encoding="utf-8")
    (configs / "guideline_sources.yml").write_text(
        """
sources:
  missing_acl:
    adapter: filesystem
    path: guidelines
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("HOSPITAL_AI_ROOT", str(root))
    reset_runtime_caches()

    with pytest.raises(ValueError, match="requires explicit access_groups"):
        ingest_guideline_sources(session)
