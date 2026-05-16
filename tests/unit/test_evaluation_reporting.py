from __future__ import annotations

from pathlib import Path

from backend.app.evaluation.reporting import RunManifest, write_referral_report


def test_write_referral_report_outputs_required_artifacts(tmp_path: Path):
    metrics = {
        "dataset": "tiny",
        "cases": 1,
        "schema_valid_rate": 1.0,
        "model_response_invalid_count": 0,
        "routing_top1_exact_accuracy": 1.0,
        "routing_top3_accuracy": 1.0,
        "null_unknown_route_rate": 0.0,
        "safe_fallback_rate": 0.0,
        "human_review_accuracy": 1.0,
        "critical_errors": 0,
        "per_route_metrics": [
            {
                "route": "radiologie",
                "support": 1,
                "true_positive": 1,
                "false_positive": 0,
                "false_negative": 0,
                "precision": 1.0,
                "recall": 1.0,
                "f1": 1.0,
            }
        ],
        "confusion_matrix": [{"expected_route": "radiologie", "actual_route": "radiologie", "count": 1}],
        "invalid_response_rows": [],
        "ocr_slice_metrics": [
            {
                "slice": "native_text",
                "cases": 1,
                "routing_top1_correct": 1,
                "routing_top1_accuracy": 1.0,
                "schema_valid": 1,
                "schema_valid_rate": 1.0,
                "critical_errors": 0,
            }
        ],
        "case_results": [
            {
                "id": "case-1",
                "passed": True,
                "expected": {"routing_target": "radiologie", "human_review_required": False},
                "actual": {
                    "routing_target": "radiologie",
                    "routing_candidates_top3": ["radiologie"],
                    "model_output_valid": True,
                    "safe_fallback": False,
                    "human_review_required": False,
                    "ocr_slice": "native_text",
                },
                "errors": [],
            }
        ],
    }
    manifest = RunManifest(
        run_id="test-run",
        generated_at_utc="2026-05-11T00:00:00+00:00",
        prompt_version="test",
        taxonomy_hash="abc",
        git_commit="abc",
        git_dirty=False,
        model_provider="test_double",
        model_id="test-double",
        endpoint_type="test_double",
        generation_max_tokens=2048,
        max_referral_text_chars=12000,
        dataset_path="demos/eval/referrals.yml",
        dataset_sha256="def",
        sample_strategy="first",
        sample_size=1,
        seed=0,
    )

    artifacts = write_referral_report(metrics, tmp_path, manifest)

    required = [
        "metrics",
        "predictions",
        "per_route_metrics",
        "confusion_matrix",
        "validation_report",
        "routing_top1_chart",
        "confusion_chart",
        "ocr_slice_chart",
        "schema_validity_chart",
        "manifest",
    ]
    for key in required:
        assert artifacts[key].exists()
    assert "ReferralOps Validation Report" in (tmp_path / "validation_report.md").read_text(encoding="utf-8")
    assert "artifact_hashes" in (tmp_path / "run_manifest.json").read_text(encoding="utf-8")
