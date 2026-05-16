from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_gitignore_covers_generated_sensitive_artifacts():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    for pattern in [
        ".env",
        "eval_hospital_ai.db",
        "*.db-wal",
        "*.db-shm",
        "data/uploads/*",
        "data/models/",
        "reports/",
        "audit_exports/",
        "*.jsonl",
    ]:
        assert pattern in gitignore


def test_dockerignore_excludes_generated_sensitive_artifacts():
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    for pattern in [
        ".env",
        ".env.*",
        "data/uploads",
        "data/models",
        "reports",
        "audit_exports",
        "*.jsonl",
    ]:
        assert pattern in dockerignore


def test_committed_validation_evidence_is_current_and_aggregate_only():
    assert not (ROOT / "VALIDATION_REPORT.md").exists()
    assert not (ROOT / "demos" / "referral_batch_large" / "metadata.jsonl").exists()

    public_docs = [
        ROOT / "README.md",
        ROOT / "demos" / "referral_batch_large" / "README.md",
        ROOT / "docs" / "live-500-pdf-review-report.md",
    ]
    combined_text = "\n".join(path.read_text(encoding="utf-8") for path in public_docs)
    for stale_fragment in ["48.8", "provisional score", "VALIDATION_REPORT.md"]:
        assert stale_fragment not in combined_text

    metrics = json.loads((ROOT / "docs" / "live_500_metrics_summary.json").read_text(encoding="utf-8"))
    assert metrics["routing_top1_accuracy"] == 0.854
    assert metrics["routing_top3_accuracy"] == 0.918
    assert "case_results" not in metrics
    assert "critical_errors" not in metrics
