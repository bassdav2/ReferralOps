from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

from backend.app.core.config import get_settings
from backend.app.db.models import Base, DocumentPage
from backend.app.db.session import create_engine_from_settings, create_sessionmaker
from backend.app.documents.registry import register_file
from backend.app.evaluation.safety import assert_destructive_eval_allowed
from backend.app.referral.routing import canonical_routing_target
from backend.app.referral.service import analyze_referral
from backend.app.security.auth import get_current_user, seed_demo_users
from backend.app.security.groups import GROUP_REFERRAL_REVIEWERS

ROOT = Path(__file__).resolve().parents[3]


@dataclass
class ReferralEvalCounts:
    routing_correct: int = 0
    routing_top3_correct: int = 0
    valid_json: int = 0
    invalid_json: int = 0
    null_or_unknown_route: int = 0
    safe_fallback: int = 0
    blocking_missing_hits: int = 0
    blocking_missing_expected: int = 0
    blocking_missing_actual: int = 0
    recommended_missing_hits: int = 0
    recommended_missing_expected: int = 0
    recommended_missing_actual: int = 0
    all_missing_hits: int = 0
    all_missing_expected: int = 0
    all_missing_actual: int = 0
    review_correct: int = 0
    review_expected_true: int = 0
    review_expected_false: int = 0
    review_true_positive: int = 0
    review_false_positive: int = 0
    review_false_negative: int = 0
    review_true_negative: int = 0
    warning_hits: int = 0
    warning_expected: int = 0

    def add(self, other: ReferralEvalCounts) -> None:
        for field in fields(self):
            setattr(self, field.name, getattr(self, field.name) + getattr(other, field.name))


def _rate(numerator: int, denominator: int, default: float = 1.0) -> float:
    return numerator / denominator if denominator else default


def _nullable_rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or precision + recall == 0:
        return None
    return 2 * precision * recall / (precision + recall)


def _wilson_interval(successes: int, total: int, z: float = 1.96) -> dict[str, float] | None:
    if total == 0:
        return None
    p = successes / total
    denominator = 1 + z**2 / total
    center = (p + z**2 / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z**2 / (4 * total)) / total) / denominator
    return {"low": max(0.0, center - margin), "high": min(1.0, center + margin)}


def _invalid_model_reasons(warnings: list[str]) -> list[str]:
    reasons: list[str] = []
    patterns = {
        "schema_validation": ["did not validate", "validation error"],
        "invalid_json": ["invalid json", "not a valid compact referral json"],
        "gateway_error": ["model gateway failed", "gateway failed"],
    }
    for warning in warnings:
        lower = warning.lower()
        for reason, needles in patterns.items():
            if any(needle in lower for needle in needles) and reason not in reasons:
                reasons.append(reason)
    return reasons


def _candidate_targets(analysis) -> list[str]:
    values: list[str] = []
    raw_values: list[str | None] = [analysis.routing_proposal.routing_target]
    raw_values.extend(
        suggestion.routing_target or suggestion.label for suggestion in analysis.secondary_routing_targets
    )
    if analysis.model_suggested_destination:
        raw_values.append(
            analysis.model_suggested_destination.mapped_to_routing_target
            or analysis.model_suggested_destination.label
        )
    for raw in raw_values:
        target = canonical_routing_target(raw)
        if target and target not in values:
            values.append(target)
    return values[:3]


def _normalized_expected_route(expected: dict[str, Any]) -> str | None:
    raw = expected.get("routing_target")
    if raw is None:
        return None
    return canonical_routing_target(str(raw)) or str(raw)


def _score_referral_analysis(
    case_id: str,
    expected: dict,
    analysis,
    *,
    ocr_slice: str = "unavailable",
) -> tuple[dict, ReferralEvalCounts, list[str]]:
    counters = ReferralEvalCounts()
    case_errors: list[str] = []
    invalid_reasons = _invalid_model_reasons(analysis.warnings)
    raw_invalid = bool(invalid_reasons)
    counters.valid_json = 0 if raw_invalid else 1
    counters.invalid_json = 1 if raw_invalid else 0

    expected_route = _normalized_expected_route(expected)
    predicted_route = canonical_routing_target(analysis.routing_proposal.routing_target)
    candidate_routes = _candidate_targets(analysis)
    counters.null_or_unknown_route = 1 if predicted_route is None else 0
    counters.safe_fallback = 1 if raw_invalid or (predicted_route is None and analysis.human_review_required) else 0

    if predicted_route == expected_route and not (expected_route is None and raw_invalid):
        counters.routing_correct = 1
    else:
        case_errors.append(f"expected routing {expected_route}, got {predicted_route}")
    if expected_route is not None and expected_route in candidate_routes:
        counters.routing_top3_correct = 1
    elif expected_route is None and predicted_route is None and not raw_invalid:
        counters.routing_top3_correct = 1

    actual_missing_by_severity = {item.field: item.severity for item in analysis.missing_items}
    actual_missing = set(actual_missing_by_severity)
    actual_blocking = {
        field for field, severity in actual_missing_by_severity.items() if severity == "blocking"
    }
    actual_recommended = {
        field for field, severity in actual_missing_by_severity.items() if severity == "recommended"
    }

    legacy_expected = set(expected.get("missing_fields", []))
    expected_blocking = set(expected.get("blocking_missing_fields", []))
    expected_recommended = set(expected.get("recommended_missing_fields", legacy_expected))
    expected_all = expected_blocking | expected_recommended

    counters.blocking_missing_expected = len(expected_blocking)
    counters.blocking_missing_actual = len(actual_blocking)
    counters.blocking_missing_hits = len(expected_blocking.intersection(actual_blocking))
    counters.recommended_missing_expected = len(expected_recommended)
    counters.recommended_missing_actual = len(actual_recommended)
    counters.recommended_missing_hits = len(expected_recommended.intersection(actual_recommended))
    counters.all_missing_expected = len(expected_all)
    counters.all_missing_actual = len(actual_missing)
    counters.all_missing_hits = len(expected_all.intersection(actual_missing))

    for field in sorted(expected_all):
        if field not in actual_missing:
            case_errors.append(f"missing field not detected: {field}")

    for field in expected.get("forbidden_missing_fields", []):
        if field in actual_missing:
            case_errors.append(f"unexpected missing field detected: {field}")

    expected_review = expected.get("human_review_required")
    if expected_review is None or analysis.human_review_required == expected_review:
        counters.review_correct = 1
    else:
        case_errors.append(f"expected human_review_required {expected_review}, got {analysis.human_review_required}")
    if expected_review is True:
        counters.review_expected_true = 1
        if analysis.human_review_required:
            counters.review_true_positive = 1
        else:
            counters.review_false_negative = 1
    elif expected_review is False:
        counters.review_expected_false = 1
        if analysis.human_review_required:
            counters.review_false_positive = 1
        else:
            counters.review_true_negative = 1

    expected_warnings = expected.get("warnings_contains", [])
    counters.warning_expected = len(expected_warnings)
    for expected_warning in expected_warnings:
        if any(expected_warning in warning for warning in analysis.warnings):
            counters.warning_hits += 1
        else:
            case_errors.append(f"expected warning containing {expected_warning}, got {analysis.warnings}")

    return (
        {
            "id": case_id,
            "passed": not case_errors,
            "expected": expected,
            "actual": {
                "routing_target": predicted_route,
                "routing_candidates_top3": candidate_routes,
                "missing_fields": sorted(actual_missing),
                "human_review_required": analysis.human_review_required,
                "warnings": analysis.warnings,
                "model_output_valid": not raw_invalid,
                "invalid_reasons": invalid_reasons,
                "safe_fallback": bool(counters.safe_fallback),
                "ocr_slice": ocr_slice,
            },
            "errors": case_errors,
        },
        counters,
        case_errors,
    )


def _metrics_from_counts(
    dataset: str,
    total: int,
    counts: ReferralEvalCounts,
    errors: list[str],
    results: list[dict],
) -> dict:
    route_results = [result for result in results if result.get("actual") is not None]
    route_labels = sorted(
        {
            route
            for result in route_results
            for route in (
                result.get("expected", {}).get("routing_target"),
                result.get("actual", {}).get("routing_target"),
            )
            if route
        }
    )
    confusion_counts: Counter[tuple[str, str]] = Counter()
    for result in route_results:
        expected_route = _normalized_expected_route(result.get("expected", {})) or "no_route"
        actual_route = result.get("actual", {}).get("routing_target") or "no_route"
        confusion_counts[(expected_route, actual_route)] += 1
    confusion_matrix = [
        {"expected_route": expected, "actual_route": actual, "count": count}
        for (expected, actual), count in sorted(confusion_counts.items())
    ]

    per_route_metrics = []
    macro_precision_values: list[float] = []
    macro_recall_values: list[float] = []
    macro_f1_values: list[float] = []
    for route in route_labels:
        tp = confusion_counts[(route, route)]
        fp = sum(
            count
            for (expected, actual), count in confusion_counts.items()
            if actual == route and expected != route
        )
        fn = sum(
            count
            for (expected, actual), count in confusion_counts.items()
            if expected == route and actual != route
        )
        support = tp + fn
        precision = _nullable_rate(tp, tp + fp)
        recall = _nullable_rate(tp, support)
        f1 = _f1(precision, recall)
        if precision is not None:
            macro_precision_values.append(precision)
        if recall is not None:
            macro_recall_values.append(recall)
        if f1 is not None:
            macro_f1_values.append(f1)
        per_route_metrics.append(
            {
                "route": route,
                "support": support,
                "true_positive": tp,
                "false_positive": fp,
                "false_negative": fn,
                "precision": precision,
                "recall": recall,
                "f1": f1,
            }
        )
    micro_tp = sum(row["true_positive"] for row in per_route_metrics)
    micro_fp = sum(row["false_positive"] for row in per_route_metrics)
    micro_fn = sum(row["false_negative"] for row in per_route_metrics)
    micro_precision = _nullable_rate(micro_tp, micro_tp + micro_fp)
    micro_recall = _nullable_rate(micro_tp, micro_tp + micro_fn)
    review_labeled = counts.review_expected_true + counts.review_expected_false
    review_precision = _nullable_rate(
        counts.review_true_positive,
        counts.review_true_positive + counts.review_false_positive,
    )
    review_recall = _nullable_rate(
        counts.review_true_positive,
        counts.review_true_positive + counts.review_false_negative,
    )
    ocr_slices: dict[str, dict[str, Any]] = {}
    for result in route_results:
        actual = result.get("actual", {})
        key = actual.get("ocr_slice") or "unavailable"
        bucket = ocr_slices.setdefault(
            key,
            {
                "slice": key,
                "cases": 0,
                "routing_top1_correct": 0,
                "schema_valid": 0,
                "critical_errors": 0,
            },
        )
        bucket["cases"] += 1
        expected_route = result.get("expected", {}).get("routing_target")
        bucket["routing_top1_correct"] += 1 if expected_route == actual.get("routing_target") else 0
        bucket["schema_valid"] += 1 if actual.get("model_output_valid") else 0
        bucket["critical_errors"] += len(result.get("errors", []))
    for bucket in ocr_slices.values():
        bucket["routing_top1_accuracy"] = _nullable_rate(bucket["routing_top1_correct"], bucket["cases"])
        bucket["schema_valid_rate"] = _nullable_rate(bucket["schema_valid"], bucket["cases"])

    key_proportions = {
        "schema_valid_rate": {
            "successes": counts.valid_json,
            "total": total,
            "wilson_95_ci": _wilson_interval(counts.valid_json, total),
        },
        "routing_top1_exact_accuracy": {
            "successes": counts.routing_correct,
            "total": total,
            "wilson_95_ci": _wilson_interval(counts.routing_correct, total),
        },
        "routing_top3_accuracy": {
            "successes": counts.routing_top3_correct,
            "total": total,
            "wilson_95_ci": _wilson_interval(counts.routing_top3_correct, total),
        },
        "human_review_accuracy": {
            "successes": counts.review_correct,
            "total": review_labeled,
            "wilson_95_ci": _wilson_interval(counts.review_correct, review_labeled),
        },
    }
    invalid_response_rows = [
        {
            "case_id": result["id"],
            "warnings": "; ".join(result.get("actual", {}).get("warnings", [])),
            "invalid_reasons": "; ".join(result.get("actual", {}).get("invalid_reasons", [])),
        }
        for result in route_results
        if not result.get("actual", {}).get("model_output_valid", True)
    ]
    return {
        "dataset": dataset,
        "cases": total,
        "routing_top1_correct": counts.routing_correct,
        "routing_top3_correct": counts.routing_top3_correct,
        "routing_top1_accuracy": _rate(counts.routing_correct, total, 0.0),
        "routing_top1_exact_accuracy": _rate(counts.routing_correct, total, 0.0),
        "routing_top3_accuracy": _rate(counts.routing_top3_correct, total, 0.0),
        "routing_precision_macro": _nullable_rate(sum(macro_precision_values), len(macro_precision_values)),
        "routing_recall_macro": _nullable_rate(sum(macro_recall_values), len(macro_recall_values)),
        "routing_f1_macro": _nullable_rate(sum(macro_f1_values), len(macro_f1_values)),
        "routing_precision_micro": micro_precision,
        "routing_recall_micro": micro_recall,
        "routing_f1_micro": _f1(micro_precision, micro_recall),
        "blocking_missing_recall": _rate(counts.blocking_missing_hits, counts.blocking_missing_expected),
        "blocking_missing_precision": _rate(counts.blocking_missing_hits, counts.blocking_missing_actual),
        "recommended_missing_recall": _rate(
            counts.recommended_missing_hits, counts.recommended_missing_expected
        ),
        "recommended_missing_precision": _rate(
            counts.recommended_missing_hits, counts.recommended_missing_actual
        ),
        "all_missing_recall": _rate(counts.all_missing_hits, counts.all_missing_expected),
        "all_missing_precision": _rate(counts.all_missing_hits, counts.all_missing_actual),
        "missing_field_recall": _rate(counts.all_missing_hits, counts.all_missing_expected),
        "missing_field_precision": _rate(counts.all_missing_hits, counts.all_missing_actual),
        "human_review_accuracy": _rate(counts.review_correct, total, 0.0),
        "human_review_match_rate": _rate(counts.review_correct, total, 0.0),
        "human_review_precision": review_precision,
        "human_review_recall": review_recall,
        "human_review_f1": _f1(review_precision, review_recall),
        "warning_match_rate": _rate(counts.warning_hits, counts.warning_expected),
        "valid_json_rate": _rate(counts.valid_json, total, 0.0),
        "valid_schema_rate": _rate(counts.valid_json, total, 0.0),
        "schema_valid_rate": _rate(counts.valid_json, total, 0.0),
        "model_response_invalid_count": counts.invalid_json,
        "null_unknown_route_rate": _rate(counts.null_or_unknown_route, total, 0.0),
        "safe_fallback_rate": _rate(counts.safe_fallback, total, 0.0),
        "per_route_metrics": per_route_metrics,
        "confusion_matrix": confusion_matrix,
        "invalid_response_rows": invalid_response_rows,
        "ocr_slice_metrics": sorted(ocr_slices.values(), key=lambda row: row["slice"]),
        "key_proportion_intervals": key_proportions,
        "top_error_cases": [
            {
                "case_id": result["id"],
                "expected_route": result.get("expected", {}).get("routing_target"),
                "actual_route": (result.get("actual") or {}).get("routing_target"),
                "errors": result.get("errors", []),
            }
            for result in results
            if result.get("errors")
        ][:10],
        "critical_errors": len(errors),
        "critical_error_details": errors,
        "case_results": results,
    }


def _ocr_slice_for_document(session, document_id: str) -> str:
    pages = (
        session.query(DocumentPage)
        .filter(DocumentPage.document_id == document_id)
        .order_by(DocumentPage.page_number.asc())
        .all()
    )
    if not pages:
        return "ocr_unavailable"
    confidences = [page.ocr_confidence for page in pages if page.ocr_confidence is not None]
    if not confidences:
        return "native_text"
    if min(confidences) < 0.5:
        return "ocr_low"
    return "ocr_ok"


def _sample_cases(
    cases: list[dict[str, Any]],
    *,
    limit: int | None,
    seed: int,
    sample_strategy: str,
) -> list[dict[str, Any]]:
    if limit is None or limit >= len(cases):
        return cases
    if limit <= 0:
        return []
    if sample_strategy == "first":
        return cases[:limit]
    rng = random.Random(seed)
    if sample_strategy == "random":
        return rng.sample(cases, limit)
    if sample_strategy != "stratified":
        raise ValueError(f"Unsupported sample_strategy: {sample_strategy}")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        route = str(case.get("expected", {}).get("routing_target") or "no_route")
        grouped[route].append(case)
    for group in grouped.values():
        rng.shuffle(group)
    selected: list[dict[str, Any]] = []
    while len(selected) < limit and any(grouped.values()):
        for route in sorted(grouped):
            group = grouped[route]
            if group:
                selected.append(group.pop())
                if len(selected) == limit:
                    break
    return selected


def evaluate_demo_referrals(
    dataset_path: Path | None = None,
    *,
    limit: int | None = None,
    seed: int = 0,
    sample_strategy: str = "first",
) -> dict:
    dataset_path = dataset_path or ROOT / "demos" / "eval" / "referrals.yml"
    data = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))
    case_specs = _sample_cases(
        list(data["cases"]),
        limit=limit,
        seed=seed,
        sample_strategy=sample_strategy,
    )

    settings = get_settings()
    assert_destructive_eval_allowed(settings)
    eval_engine = create_engine_from_settings(settings)
    eval_session_local = create_sessionmaker(eval_engine)
    Base.metadata.drop_all(bind=eval_engine)
    Base.metadata.create_all(bind=eval_engine)

    counts = ReferralEvalCounts()
    case_results: list[dict] = []
    critical_errors: list[str] = []

    with eval_session_local() as session:
        seed_demo_users(session)
        for case_spec in case_specs:
            user = get_current_user(case_spec["user"])
            path = ROOT / case_spec["path"]
            expected = case_spec["expected"]

            document = register_file(
                session,
                path,
                title=case_spec["id"],
                access_groups=case_spec.get("access_groups", [GROUP_REFERRAL_REVIEWERS]),
                contains_patient_data=True,
            )

            try:
                case = analyze_referral(session, document.id, user)
                result, case_counts, case_errors = _score_referral_analysis(
                    case_spec["id"],
                    expected,
                    case.analysis,
                    ocr_slice=_ocr_slice_for_document(session, document.id),
                )
                case_results.append(result)
                counts.add(case_counts)
                critical_errors.extend(f"{case_spec['id']}: {error}" for error in case_errors)

            except Exception as exc:
                critical_errors.append(f"{case_spec['id']}: exception {exc}")
                case_results.append(
                    {
                        "id": case_spec["id"],
                        "passed": False,
                        "expected": expected,
                        "actual": None,
                        "errors": [f"exception {exc}"],
                    }
                )

    metrics = _metrics_from_counts(data["dataset"], len(case_specs), counts, critical_errors, case_results)
    metrics["dataset_path"] = str(dataset_path)
    metrics["sample_strategy"] = sample_strategy
    metrics["sample_size"] = len(case_specs)
    metrics["seed"] = seed
    return metrics


def markdown_table(metrics: dict) -> str:
    rows = [
        ("Cases", metrics["cases"]),
        ("Routing Top-1 Accuracy", metrics["routing_top1_accuracy"]),
        ("Routing Top-3 Accuracy", metrics["routing_top3_accuracy"]),
        ("Schema Valid Rate", metrics["schema_valid_rate"]),
        ("Invalid Model Responses", metrics["model_response_invalid_count"]),
        ("Null/Unknown Route Rate", metrics["null_unknown_route_rate"]),
        ("Safe Fallback Rate", metrics["safe_fallback_rate"]),
        ("Blocking Missing Recall", metrics["blocking_missing_recall"]),
        ("Blocking Missing Precision", metrics["blocking_missing_precision"]),
        ("Recommended Missing Recall", metrics["recommended_missing_recall"]),
        ("Recommended Missing Precision", metrics["recommended_missing_precision"]),
        ("All Missing Recall", metrics["all_missing_recall"]),
        ("All Missing Precision", metrics["all_missing_precision"]),
        ("Human Review Match Rate", metrics["human_review_match_rate"]),
        ("Valid Schema Rate", metrics["valid_schema_rate"]),
        ("Critical Errors", metrics["critical_errors"]),
    ]
    body = "\n".join(f"| {name} | {value} |" for name, value in rows)
    return "| Metric | Value |\n|---|---|\n" + body
