from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path

import yaml

from backend.app.core.config import get_settings
from backend.app.db.models import Base
from backend.app.db.session import create_engine_from_settings, create_sessionmaker
from backend.app.evaluation.safety import assert_destructive_eval_allowed
from backend.app.rag.answerer import answer_guideline_question
from backend.app.rag.ingest import ingest_guideline_sources
from backend.app.security.auth import get_current_user, seed_demo_users

ROOT = Path(__file__).resolve().parents[3]


@dataclass
class GuidelineEvalCounts:
    correct_confidence: int = 0
    correct_source: int = 0
    source_expected: int = 0
    no_answer_correct: int = 0
    no_answer_expected: int = 0
    answer_contains_hits: int = 0
    answer_contains_expected: int = 0
    acl_violations: int = 0
    patient_refusals: int = 0
    ungrounded_answers_blocked: int = 0

    def add(self, other: GuidelineEvalCounts) -> None:
        for field in fields(self):
            setattr(self, field.name, getattr(self, field.name) + getattr(other, field.name))


def _rate(numerator: int, denominator: int, default: float = 1.0) -> float:
    return numerator / denominator if denominator else default


def _score_guideline_answer(spec: dict, answer) -> tuple[dict, GuidelineEvalCounts, list[str]]:
    expected = spec["expected"]
    counters = GuidelineEvalCounts()
    question_errors: list[str] = []
    if "ungrounded_answer_blocked" in answer.safety_flags:
        counters.ungrounded_answers_blocked = 1

    if answer.confidence == expected.get("confidence"):
        counters.correct_confidence = 1
    else:
        question_errors.append(f"expected confidence {expected.get('confidence')}, got {answer.confidence}")

    expected_source = expected.get("source_title_contains")
    if expected_source:
        counters.source_expected = 1
        if any(expected_source.lower() in source.title.lower() for source in answer.sources):
            counters.correct_source = 1
        else:
            question_errors.append(
                f"expected source containing {expected_source}, got {[source.title for source in answer.sources]}"
            )
    elif expected.get("sources_count") == 0:
        counters.no_answer_expected = 1
        if not answer.sources:
            counters.no_answer_correct = 1
        else:
            counters.acl_violations = 1
            question_errors.append(f"expected no sources, got {[source.title for source in answer.sources]}")

    for needle in expected.get("answer_contains", []):
        counters.answer_contains_expected += 1
        if needle.lower() in answer.answer.lower():
            counters.answer_contains_hits += 1
        else:
            question_errors.append(f"expected answer containing {needle}, got {answer.answer}")

    for flag in expected.get("safety_flags_contains", []):
        if flag in answer.safety_flags:
            counters.patient_refusals += 1
        else:
            question_errors.append(f"missing safety flag {flag}")

    return (
        {
            "id": spec["id"],
            "passed": not question_errors,
            "expected": expected,
            "actual": {
                "confidence": answer.confidence,
                "source_titles": [source.title for source in answer.sources],
                "sources_count": len(answer.sources),
                "safety_flags": answer.safety_flags,
            },
            "errors": question_errors,
        },
        counters,
        question_errors,
    )


def _metrics_from_counts(
    dataset: str,
    total: int,
    counts: GuidelineEvalCounts,
    errors: list[str],
    results: list[dict],
) -> dict:
    return {
        "dataset": dataset,
        "questions": total,
        "confidence_accuracy": _rate(counts.correct_confidence, total, 0.0),
        "source_match_count": counts.correct_source,
        "source_match_rate": _rate(counts.correct_source, counts.source_expected),
        "expected_source_hit_rate": _rate(counts.correct_source, counts.source_expected),
        "answer_contains_rate": _rate(counts.answer_contains_hits, counts.answer_contains_expected),
        "answer_accuracy_by_contains": _rate(counts.answer_contains_hits, counts.answer_contains_expected),
        "no_answer_correct": counts.no_answer_correct,
        "no_answer_accuracy": _rate(counts.no_answer_correct, counts.no_answer_expected),
        "acl_violations": counts.acl_violations,
        "patient_specific_refusals": counts.patient_refusals,
        "ungrounded_answers_blocked": counts.ungrounded_answers_blocked,
        "critical_errors": len(errors),
        "critical_error_details": errors,
        "question_results": results,
    }


def evaluate_demo_guidelines(dataset_path: Path | None = None) -> dict:
    dataset_path = dataset_path or ROOT / "demos" / "eval" / "guidelines.yml"
    data = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))

    settings = get_settings()
    assert_destructive_eval_allowed(settings)
    eval_engine = create_engine_from_settings(settings)
    eval_session_local = create_sessionmaker(eval_engine)
    Base.metadata.drop_all(bind=eval_engine)
    Base.metadata.create_all(bind=eval_engine)

    counts = GuidelineEvalCounts()
    question_results: list[dict] = []
    errors: list[str] = []

    with eval_session_local() as session:
        seed_demo_users(session)
        ingest_guideline_sources(session)

        for spec in data["questions"]:
            question_errors: list[str] = []
            try:
                user = get_current_user(spec["user"])
                answer = answer_guideline_question(session, spec["question"], user)
                result, question_counts, question_errors = _score_guideline_answer(spec, answer)
                counts.add(question_counts)
            except Exception as exc:
                question_errors.append(f"exception {exc}")
                result = {
                    "id": spec["id"],
                    "passed": not question_errors,
                    "expected": spec["expected"],
                    "actual": None,
                    "errors": question_errors,
                }
            question_results.append(result)
            errors.extend(f"{spec['id']}: {error}" for error in question_errors)

    return _metrics_from_counts(data["dataset"], len(data["questions"]), counts, errors, question_results)


def markdown_table(metrics: dict) -> str:
    rows = [
        ("Questions", metrics["questions"]),
        ("Confidence Accuracy", metrics["confidence_accuracy"]),
        ("Expected Source Hit Rate", metrics["expected_source_hit_rate"]),
        ("Answer Accuracy By Contains", metrics["answer_accuracy_by_contains"]),
        ("No-Answer Accuracy", metrics["no_answer_accuracy"]),
        ("ACL Violations", metrics["acl_violations"]),
        ("Patient-Specific Refusals", metrics["patient_specific_refusals"]),
        ("Ungrounded Answers Blocked", metrics["ungrounded_answers_blocked"]),
        ("Critical Errors", metrics["critical_errors"]),
    ]
    body = "\n".join(f"| {name} | {value} |" for name, value in rows)
    return "| Metric | Value |\n|---|---|\n" + body
