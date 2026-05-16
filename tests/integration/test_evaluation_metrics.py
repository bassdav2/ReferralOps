from __future__ import annotations

from pathlib import Path

from backend.app.evaluation.metrics_rag import evaluate_demo_guidelines
from backend.app.evaluation.metrics_referrals import evaluate_demo_referrals
from backend.app.referral.schemas import ReferralAnalysis


def test_referral_evaluation_outputs_required_metric_names():
    metrics = evaluate_demo_referrals()

    assert metrics["cases"] == 2
    assert "valid_schema_rate" in metrics
    assert "schema_valid_rate" in metrics
    assert "model_response_invalid_count" in metrics
    assert "routing_top3_accuracy" in metrics
    assert "per_route_metrics" in metrics
    assert "confusion_matrix" in metrics
    assert "ocr_slice_metrics" in metrics
    assert "missing_field_recall" in metrics
    assert "missing_field_precision" in metrics
    assert "human_review_match_rate" in metrics
    assert metrics["case_results"]


def test_referral_evaluation_metrics_change_when_expected_label_is_wrong(tmp_path: Path):
    sample = tmp_path / "wrong_label_referral.txt"
    sample.write_text("Zuweisung wegen Thoraxbeschwerden und Dyspnoe.", encoding="utf-8")
    dataset = tmp_path / "referrals.yml"
    dataset.write_text(
        f"""
dataset: wrong_referral_label
cases:
  - id: wrong
    path: {sample}
    user: sekretariat_kardiologie
    access_groups: [referral_reviewers]
    expected:
      routing_target: radiologie
      human_review_required: true
""",
        encoding="utf-8",
    )

    metrics = evaluate_demo_referrals(dataset)

    assert metrics["routing_top1_accuracy"] == 0.0
    assert metrics["critical_errors"] > 0


def test_guideline_evaluation_outputs_required_metric_names():
    metrics = evaluate_demo_guidelines()

    assert metrics["questions"] == 6
    assert "answer_accuracy_by_contains" in metrics
    assert "expected_source_hit_rate" in metrics
    assert "ungrounded_answers_blocked" in metrics
    assert metrics["question_results"]


def test_guideline_evaluation_metrics_change_when_expected_source_is_wrong(tmp_path: Path):
    dataset = tmp_path / "guidelines.yml"
    dataset.write_text(
        """
dataset: wrong_guideline_source
questions:
  - id: wrong_source
    user: it_admin
    question: Wie beantrage ich einen KIS-Zugang?
    expected:
      confidence: high
      source_title_contains: Wrong Source
      answer_contains:
        - KIS
""",
        encoding="utf-8",
    )

    metrics = evaluate_demo_guidelines(dataset)

    assert metrics["source_match_rate"] == 0.0
    assert metrics["critical_errors"] > 0


def test_default_synthetic_evaluations_report_zero_critical_errors():
    referral_metrics = evaluate_demo_referrals()
    guideline_metrics = evaluate_demo_guidelines()

    assert referral_metrics["critical_errors"] == 0
    assert referral_metrics["valid_json_rate"] >= 0.95
    assert referral_metrics["blocking_missing_recall"] >= 0.90
    assert guideline_metrics["critical_errors"] == 0
    assert guideline_metrics["acl_violations"] == 0
    assert guideline_metrics["no_answer_accuracy"] >= 0.90


def test_guideline_evaluation_records_failed_questions(monkeypatch, tmp_path: Path):
    dataset = tmp_path / "guidelines.yml"
    dataset.write_text(
        """
dataset: one_bad_question
questions:
  - id: bad
    user: it_admin
    question: Wie beantrage ich einen KIS-Zugang?
    expected:
      confidence: high
""",
        encoding="utf-8",
    )

    def boom(*args, **kwargs):
        raise RuntimeError("model failed")

    monkeypatch.setattr("backend.app.evaluation.metrics_rag.answer_guideline_question", boom)
    metrics = evaluate_demo_guidelines(dataset)

    assert metrics["critical_errors"] == 1
    assert metrics["question_results"][0]["passed"] is False
    assert metrics["question_results"][0]["actual"] is None


def test_referral_valid_schema_rate_counts_validation_fallback(monkeypatch, tmp_path: Path):
    sample = tmp_path / "sample.txt"
    sample.write_text("Zuweisung wegen Thoraxbeschwerden.", encoding="utf-8")
    dataset = tmp_path / "referrals.yml"
    dataset.write_text(
        f"""
dataset: invalid_schema_case
cases:
  - id: invalid
    path: {sample}
    user: sekretariat_kardiologie
    access_groups: [referral_reviewers]
    expected:
      routing_target:
      human_review_required: true
""",
        encoding="utf-8",
    )

    class FakeCase:
        analysis = ReferralAnalysis(
            document_id="fake",
            human_review_required=True,
            warnings=["Model response did not validate against ReferralAnalysis schema."],
        )

    monkeypatch.setattr("backend.app.evaluation.metrics_referrals.analyze_referral", lambda *args, **kwargs: FakeCase())

    metrics = evaluate_demo_referrals(dataset)

    assert metrics["valid_schema_rate"] == 0.0
    assert metrics["case_results"][0]["actual"]["model_output_valid"] is False
