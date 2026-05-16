from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.db.models import GuidelineChunk, GuidelineDocument
from backend.app.rag.ingest import ingest_guideline_sources


def run_guideline_ingest_refresh_scenario(monkeypatch, reset_runtime_caches, session, tmp_path: Path) -> None:
    root = tmp_path
    docs = root / "guidelines"
    configs = root / "configs"
    docs.mkdir()
    configs.mkdir()
    (docs / "policy.md").write_text("# Policy\n\nKIS-Zugang beantragen.", encoding="utf-8")
    config_path = configs / "guideline_sources.yml"
    config_path.write_text(
        """
sources:
  test_guidelines:
    adapter: filesystem
    path: guidelines
    owner_department: IT
    access_groups: [all_staff]
    escalation_contact: old@example.invalid
    default_status: active
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("HOSPITAL_AI_ROOT", str(root))
    reset_runtime_caches()

    first = ingest_guideline_sources(session)
    document = session.query(GuidelineDocument).one()
    assert first["created"] == 1
    assert first["chunks_written"] > 0
    assert document.access_groups == ["all_staff"]
    assert document.escalation_contact == "old@example.invalid"

    config_path.write_text(
        """
sources:
  test_guidelines:
    adapter: filesystem
    path: guidelines
    owner_department: Security
    access_groups: [it_users]
    escalation_contact: new@example.invalid
    default_status: active
""",
        encoding="utf-8",
    )

    second = ingest_guideline_sources(session)
    document = session.query(GuidelineDocument).one()
    assert second["skipped"] == 1
    assert second["chunks_written"] == 0
    assert document.owner_department == "Security"
    assert document.access_groups == ["it_users"]
    assert document.escalation_contact == "new@example.invalid"


def test_guideline_ingest_refreshes_existing_metadata(monkeypatch, reset_runtime_caches, session, tmp_path: Path):
    run_guideline_ingest_refresh_scenario(monkeypatch, reset_runtime_caches, session, tmp_path)


def test_guideline_ingestion_preserves_source_metadata(monkeypatch, reset_runtime_caches, session, tmp_path: Path):
    run_guideline_ingest_refresh_scenario(monkeypatch, reset_runtime_caches, session, tmp_path)


def run_guideline_changed_source_scenario(monkeypatch, reset_runtime_caches, session, tmp_path: Path) -> None:
    root = tmp_path
    docs = root / "guidelines"
    configs = root / "configs"
    docs.mkdir()
    configs.mkdir()
    policy = docs / "policy.md"
    policy.write_text("# Policy\n\nKIS-Zugang beantragen.", encoding="utf-8")
    (configs / "guideline_sources.yml").write_text(
        """
sources:
  test_guidelines:
    adapter: filesystem
    path: guidelines
    owner_department: IT
    access_groups: [all_staff]
    default_status: active
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("HOSPITAL_AI_ROOT", str(root))
    reset_runtime_caches()

    first = ingest_guideline_sources(session)
    first_chunk_ids = {chunk.id for chunk in session.query(GuidelineChunk).all()}
    second = ingest_guideline_sources(session)
    second_chunk_ids = {chunk.id for chunk in session.query(GuidelineChunk).all()}
    policy.write_text("# Policy\n\nKIS-Zugang beantragen.\n\n## DMS\n\nFreigabe erforderlich.", encoding="utf-8")
    third = ingest_guideline_sources(session)
    third_chunk_ids = {chunk.id for chunk in session.query(GuidelineChunk).all()}

    assert first["documents"] == 1
    assert first["created"] == 1
    assert first["chunks_written"] > 0
    assert second["documents"] == 0
    assert second["skipped"] == 1
    assert second["chunks_written"] == 0
    assert second_chunk_ids == first_chunk_ids
    assert third["documents"] == 1
    assert third["changed"] == 1
    assert third["chunks_written"] > 0
    assert third_chunk_ids
    assert third_chunk_ids.isdisjoint(first_chunk_ids)


def test_guideline_ingest_skips_unchanged_and_replaces_changed_chunks(
    monkeypatch, reset_runtime_caches, session, tmp_path: Path
):
    run_guideline_changed_source_scenario(monkeypatch, reset_runtime_caches, session, tmp_path)


def test_guideline_ingestion_is_idempotent(monkeypatch, reset_runtime_caches, session, tmp_path: Path):
    root = tmp_path
    docs = root / "guidelines"
    configs = root / "configs"
    docs.mkdir()
    configs.mkdir()
    (docs / "policy.md").write_text("# Policy\n\nKIS-Zugang beantragen.", encoding="utf-8")
    (configs / "guideline_sources.yml").write_text(
        """
sources:
  test_guidelines:
    adapter: filesystem
    path: guidelines
    owner_department: IT
    access_groups: [all_staff]
    default_status: active
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("HOSPITAL_AI_ROOT", str(root))
    reset_runtime_caches()

    ingest_guideline_sources(session)
    document_count = session.query(GuidelineDocument).count()
    chunk_count = session.query(GuidelineChunk).count()
    second = ingest_guideline_sources(session)

    assert second["skipped"] == 1
    assert session.query(GuidelineDocument).count() == document_count
    assert session.query(GuidelineChunk).count() == chunk_count


def test_guideline_ingestion_updates_changed_source_without_duplicate_active_chunks(
    monkeypatch, reset_runtime_caches, session, tmp_path: Path
):
    run_guideline_changed_source_scenario(monkeypatch, reset_runtime_caches, session, tmp_path)


def run_guideline_missing_access_groups_scenario(monkeypatch, reset_runtime_caches, session, tmp_path: Path) -> None:
    root = tmp_path
    docs = root / "guidelines"
    configs = root / "configs"
    docs.mkdir()
    configs.mkdir()
    (docs / "policy.md").write_text("# Policy\n\nKIS-Zugang beantragen.", encoding="utf-8")
    (configs / "guideline_sources.yml").write_text(
        """
sources:
  test_guidelines:
    adapter: filesystem
    path: guidelines
    owner_department: IT
    default_status: active
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("HOSPITAL_AI_ROOT", str(root))
    reset_runtime_caches()

    with pytest.raises(ValueError, match="requires explicit access_groups"):
        ingest_guideline_sources(session)


def test_guideline_ingest_requires_explicit_access_groups(
    monkeypatch, reset_runtime_caches, session, tmp_path: Path
):
    run_guideline_missing_access_groups_scenario(monkeypatch, reset_runtime_caches, session, tmp_path)


def test_guideline_source_missing_access_groups_fails_validation(
    monkeypatch, reset_runtime_caches, session, tmp_path: Path
):
    run_guideline_missing_access_groups_scenario(monkeypatch, reset_runtime_caches, session, tmp_path)
