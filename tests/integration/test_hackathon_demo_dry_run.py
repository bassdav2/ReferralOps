from __future__ import annotations

from scripts.demo_video_dry_run import run_demo_video_dry_run


def test_demo_video_dry_run_creates_pipeline_events_and_outputs(isolated_project_root, reset_runtime_caches):
    (isolated_project_root / "configs" / "referral_sources.yml").write_text(
        """
sources:
  demo_referral_filesystem:
    adapter: filesystem
    path: data/referral_inbox
    access_groups: [referral_reviewers]
    contains_patient_data: true
    source_system: demo_referral_filesystem
    analyze_on_ingest: true
    analyze_user: sekretariat_kardiologie
""",
        encoding="utf-8",
    )
    reset_runtime_caches()

    result = run_demo_video_dry_run(limit=4)

    assert result["pipeline_events"] > 0
    assert result["outputs_written"] > 0
    assert result["worklist_items"] > 0
    assert result["summary"]["total_documents"] > 0
