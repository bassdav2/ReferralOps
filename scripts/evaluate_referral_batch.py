from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import random
import shutil
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("APP_ENV", "demo")
os.environ.setdefault("DATABASE_URL", "sqlite:///./eval_referral_batch.db")
os.environ.setdefault("MODEL_PROVIDER", "gemma_vllm")
os.environ.setdefault("EMBEDDING_PROVIDER", "lexical_only")
os.environ.setdefault("NO_EXTERNAL_AI_CALLS", "true")
os.environ.setdefault("GUIDELINE_EXTRACTIVE_MODE", "true")
os.environ.setdefault("DEMO_PRELOAD_REFERRALS", "false")

from backend.app.core.config import get_settings
from backend.app.db.models import Base
from backend.app.db.session import create_engine_from_settings, create_sessionmaker
from backend.app.documents.registry import register_file
from backend.app.evaluation.reporting import build_run_manifest, write_referral_report
from backend.app.evaluation.safety import assert_destructive_eval_allowed
from backend.app.referral.prompts import REFERRAL_PROMPT_VERSION
from backend.app.referral.routing import canonical_routing_target
from backend.app.referral.schemas import ReferralAnalysis
from backend.app.referral.service import analyze_referral
from backend.app.security.auth import get_current_user, seed_demo_users
from backend.app.security.groups import GROUP_REFERRAL_REVIEWERS

LABEL_COLUMNS = [
    "pdf_adjudicated_routing_target",
    "adjudicated_routing_target",
    "adjudicated_target",
    "routing_target",
    "primary_target_department",
    "target_department",
    "department",
    "route",
]

DEFAULT_METADATA_PATH = ROOT / "demos" / "referral_batch_large" / "metadata.csv"
DEFAULT_ADJUDICATED_LABELS_PATH = ROOT / "demos" / "referral_batch_large" / "pdf_adjudicated_labels.csv"


def default_labels_path() -> Path:
    return DEFAULT_ADJUDICATED_LABELS_PATH if DEFAULT_ADJUDICATED_LABELS_PATH.exists() else DEFAULT_METADATA_PATH


def _assert_live_runtime_ready() -> None:
    missing: list[str] = []
    for module in ("pypdfium2", "pytesseract"):
        if importlib.util.find_spec(module) is None:
            missing.append(module)
    if shutil.which("tesseract") is None:
        missing.append("tesseract binary")
    if missing:
        raise SystemExit(
            "Live PDF evaluation needs the repo OCR runtime. Missing: "
            + ", ".join(missing)
            + ". Run `make bootstrap` if needed, then use `.venv/bin/python "
            "scripts/evaluate_referral_batch.py ...` from the repo root."
        )


def _read_label_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() in {".yml", ".yaml"}:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return [
            {
                "case_id": case["id"],
                "path": case.get("path"),
                "file_name": Path(case.get("path", case["id"])).name,
                "routing_target": case.get("expected", {}).get("routing_target"),
                "human_review_required": case.get("expected", {}).get("human_review_required"),
            }
            for case in data.get("cases", [])
        ]
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _route_label(row: dict[str, Any]) -> str | None:
    for column in LABEL_COLUMNS:
        value = row.get(column)
        if value not in (None, ""):
            return canonical_routing_target(str(value)) or str(value)
    return None


def _bool_label(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    return None


def _row_key(row: dict[str, Any]) -> str:
    return str(row.get("file_name") or row.get("case_id") or row.get("id") or "")


def _sample_rows(rows: list[dict[str, Any]], *, limit: int | None, seed: int, strategy: str) -> list[dict[str, Any]]:
    if limit is None or limit >= len(rows):
        return rows
    if strategy == "first":
        return rows[:limit]
    rng = random.Random(seed)
    if strategy == "random":
        return rng.sample(rows, limit)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_route_label(row) or "no_route", []).append(row)
    for group in grouped.values():
        rng.shuffle(group)
    selected: list[dict[str, Any]] = []
    while len(selected) < limit and any(grouped.values()):
        for key in sorted(grouped):
            if grouped[key]:
                selected.append(grouped[key].pop())
                if len(selected) == limit:
                    break
    return selected


def _candidate_file_name(row: dict[str, Any]) -> str | None:
    for column in ("file_name", "filename", "pdf", "pdf_file", "document", "document_file"):
        value = row.get(column)
        if value:
            return str(value)
    path = row.get("path") or row.get("pdf_path") or row.get("document_path")
    return Path(str(path)).name if path else None


def _resolve_pdf_path(row: dict[str, Any], *, labels_path: Path, pdf_dir: Path | None) -> Path:
    raw_path = row.get("path") or row.get("pdf_path") or row.get("document_path")
    candidates: list[Path] = []
    if raw_path:
        path = Path(str(raw_path))
        if path.is_absolute():
            candidates.append(path)
        else:
            candidates.extend([ROOT / path, labels_path.parent / path])
    file_name = _candidate_file_name(row)
    if file_name:
        if pdf_dir:
            candidates.append(pdf_dir / file_name)
        candidates.extend([labels_path.parent / file_name, labels_path.parent / "pdfs" / file_name])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    searched = ", ".join(str(candidate) for candidate in candidates) or "no candidate paths"
    raise FileNotFoundError(f"Could not resolve PDF for {_row_key(row)}; searched: {searched}")


def _analysis_from_fixture(row: dict[str, Any], fixture: str) -> ReferralAnalysis:
    expected_route = _route_label(row)
    route = expected_route
    warnings: list[str] = []
    if fixture == "invalid":
        route = None
        warnings = ["Model response did not validate against compact ReferralModelOutput schema."]
    elif fixture == "truncated":
        route = None
        warnings = ["Local model gateway failed or returned invalid JSON. Human review required."]
    elif fixture == "null-route":
        route = None
    elif fixture == "multi-route":
        route = expected_route
    elif fixture == "unknown-alias":
        route = "unknown_external_route"
    return ReferralAnalysis(
        document_id=str(row.get("case_id") or row.get("file_name") or "fixture"),
        document_type="referral",
        routing_proposal={"routing_target": route, "confidence": 0.82 if route else 0.2},
        secondary_routing_targets=[{"routing_target": "radiologie"}, {"routing_target": "kardiologie"}]
        if fixture == "multi-route"
        else [],
        human_review_required=_bool_label(row.get("human_review_required")) if fixture == "valid" else True,
        warnings=warnings,
    )


def _load_db_predictions(rows: list[dict[str, Any]], db_path: Path) -> dict[str, ReferralAnalysis]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    records = connection.execute(
        """
        select d.title, c.analysis_json
        from referral_cases c
        join documents d on d.id = c.document_id
        order by d.title
        """
    ).fetchall()
    by_title: dict[str, ReferralAnalysis] = {}
    for record in records:
        raw = record["analysis_json"]
        payload = json.loads(raw) if isinstance(raw, str) else raw
        by_title[str(record["title"])] = ReferralAnalysis.model_validate(payload)
    predictions: dict[str, ReferralAnalysis] = {}
    for row in rows:
        title = _row_key(row)
        if title in by_title:
            predictions[title] = by_title[title]
    return predictions


def _run_live_predictions(
    rows: list[dict[str, Any]],
    *,
    labels_path: Path,
    pdf_dir: Path | None,
    user_id: str,
) -> dict[str, ReferralAnalysis]:
    settings = get_settings()
    assert_destructive_eval_allowed(settings)
    engine = create_engine_from_settings(settings)
    session_local = create_sessionmaker(engine)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    predictions: dict[str, ReferralAnalysis] = {}
    with session_local() as session:
        seed_demo_users(session)
        user = get_current_user(user_id)
        for row in rows:
            key = _row_key(row)
            try:
                pdf_path = _resolve_pdf_path(row, labels_path=labels_path, pdf_dir=pdf_dir)
                document = register_file(
                    session,
                    pdf_path,
                    title=key or pdf_path.name,
                    access_groups=[GROUP_REFERRAL_REVIEWERS],
                    contains_patient_data=True,
                )
                predictions[key] = analyze_referral(session, document.id, user).analysis
            except Exception as exc:
                predictions[key] = ReferralAnalysis(
                    document_id=key or "live-eval-error",
                    document_type="unknown",
                    human_review_required=True,
                    warnings=[f"Live batch evaluation failed before model scoring: {type(exc).__name__}."],
                )
    return predictions


def _invalid_reasons(analysis: ReferralAnalysis) -> list[str]:
    reasons: list[str] = []
    for warning in analysis.warnings:
        lower = warning.lower()
        if "did not validate" in lower and "schema_validation" not in reasons:
            reasons.append("schema_validation")
        if "invalid json" in lower and "invalid_json" not in reasons:
            reasons.append("invalid_json")
        if "gateway failed" in lower and "gateway_error" not in reasons:
            reasons.append("gateway_error")
        if "live batch evaluation failed" in lower and "live_eval_error" not in reasons:
            reasons.append("live_eval_error")
    return reasons


def _metrics(rows: list[dict[str, Any]], predictions: dict[str, ReferralAnalysis], dataset: str) -> dict[str, Any]:
    case_results: list[dict[str, Any]] = []
    confusion: Counter[tuple[str, str]] = Counter()
    top1 = 0
    top3 = 0
    valid = 0
    invalid = 0
    safe_fallback = 0
    null_routes = 0
    review_correct = 0
    review_labeled = 0
    for row in rows:
        case_id = str(row.get("case_id") or row.get("id") or row.get("file_name") or len(case_results))
        expected = _route_label(row)
        expected_review = _bool_label(row.get("human_review_required"))
        analysis = predictions.get(_row_key(row) or case_id)
        errors: list[str] = []
        if analysis is None:
            actual = None
            invalid += 1
            safe_fallback += 1
            errors.append("No prediction found for label row.")
        else:
            reasons = _invalid_reasons(analysis)
            actual_route = canonical_routing_target(analysis.routing_proposal.routing_target)
            raw_candidates = [actual_route]
            raw_candidates.extend(
                canonical_routing_target(suggestion.routing_target or suggestion.label)
                for suggestion in analysis.secondary_routing_targets
            )
            candidates = [
                candidate
                for index, candidate in enumerate(raw_candidates)
                if candidate and candidate not in raw_candidates[:index]
            ][:3]
            if reasons:
                invalid += 1
            else:
                valid += 1
            if actual_route is None:
                null_routes += 1
            if reasons or (actual_route is None and analysis.human_review_required):
                safe_fallback += 1
            if actual_route == expected and not (expected is None and reasons):
                top1 += 1
            else:
                errors.append(f"expected routing {expected}, got {actual_route}")
            if expected in candidates or (expected is None and actual_route is None and not reasons):
                top3 += 1
            if expected_review is not None:
                review_labeled += 1
                if analysis.human_review_required == expected_review:
                    review_correct += 1
            confusion[(expected or "no_route", actual_route or "no_route")] += 1
            ocr_slice = (
                analysis.ocr_status
                if analysis.ocr_status != "unknown"
                else row.get("ocr_status") or "unavailable"
            )
            actual = {
                "routing_target": actual_route,
                "routing_candidates_top3": candidates,
                "human_review_required": analysis.human_review_required,
                "model_output_valid": not reasons,
                "safe_fallback": bool(reasons or (actual_route is None and analysis.human_review_required)),
                "warnings": analysis.warnings,
                "invalid_reasons": reasons,
                "ocr_slice": ocr_slice,
            }
        case_results.append(
            {
                "id": case_id,
                "passed": not errors,
                "expected": {"routing_target": expected, "human_review_required": expected_review},
                "actual": actual,
                "errors": errors,
            }
        )
    total = len(rows)
    per_route = []
    labels = sorted({label for pair in confusion for label in pair if label != "no_route"})
    for route in labels:
        tp = confusion[(route, route)]
        fp = sum(count for (expected, actual), count in confusion.items() if actual == route and expected != route)
        fn = sum(count for (expected, actual), count in confusion.items() if expected == route and actual != route)
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        if precision is None or recall is None or precision + recall == 0:
            f1 = None
        else:
            f1 = 2 * precision * recall / (precision + recall)
        per_route.append(
            {
                "route": route,
                "support": tp + fn,
                "true_positive": tp,
                "false_positive": fp,
                "false_negative": fn,
                "precision": precision,
                "recall": recall,
                "f1": f1,
            }
        )
    ocr_slices: dict[str, dict[str, Any]] = {}
    for result in case_results:
        actual = result.get("actual") or {}
        key = actual.get("ocr_slice") or "unavailable"
        bucket = ocr_slices.setdefault(
            key,
            {
                "slice": key,
                "cases": 0,
                "routing_top1_correct": 0,
                "model_response_invalid_count": 0,
                "null_unknown_route_count": 0,
                "safe_fallback_count": 0,
            },
        )
        bucket["cases"] += 1
        if result.get("expected", {}).get("routing_target") == actual.get("routing_target") and actual.get(
            "model_output_valid", False
        ):
            bucket["routing_top1_correct"] += 1
        if not actual.get("model_output_valid", False):
            bucket["model_response_invalid_count"] += 1
        if actual.get("routing_target") is None:
            bucket["null_unknown_route_count"] += 1
        if actual.get("safe_fallback"):
            bucket["safe_fallback_count"] += 1
    for bucket in ocr_slices.values():
        cases = bucket["cases"]
        bucket["routing_top1_accuracy"] = bucket["routing_top1_correct"] / cases if cases else 0.0
        bucket["schema_valid_rate"] = 1 - (bucket["model_response_invalid_count"] / cases if cases else 0.0)
        bucket["null_unknown_route_rate"] = bucket["null_unknown_route_count"] / cases if cases else 0.0
        bucket["safe_fallback_rate"] = bucket["safe_fallback_count"] / cases if cases else 0.0

    return {
        "dataset": dataset,
        "cases": total,
        "routing_top1_correct": top1,
        "routing_top1_accuracy": top1 / total if total else 0.0,
        "routing_top1_exact_accuracy": top1 / total if total else 0.0,
        "routing_top3_accuracy": top3 / total if total else 0.0,
        "schema_valid_rate": valid / total if total else 0.0,
        "valid_schema_rate": valid / total if total else 0.0,
        "model_response_invalid_count": invalid,
        "null_unknown_route_rate": null_routes / total if total else 0.0,
        "safe_fallback_rate": safe_fallback / total if total else 0.0,
        "human_review_accuracy": review_correct / review_labeled if review_labeled else None,
        "human_review_precision": None,
        "human_review_recall": None,
        "human_review_f1": None,
        "per_route_metrics": per_route,
        "confusion_matrix": [
            {"expected_route": expected, "actual_route": actual, "count": count}
            for (expected, actual), count in sorted(confusion.items())
        ],
        "invalid_response_rows": [
            {"case_id": result["id"], "warnings": "; ".join((result.get("actual") or {}).get("warnings", []))}
            for result in case_results
            if not (result.get("actual") or {}).get("model_output_valid", False)
        ],
        "ocr_slice_metrics": sorted(ocr_slices.values(), key=lambda row: row["slice"]),
        "critical_errors": sum(1 for result in case_results if result["errors"]),
        "critical_error_details": [f"{result['id']}: {error}" for result in case_results for error in result["errors"]],
        "case_results": case_results,
        "sample_size": total,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic referral batch evaluator for local Gemma endpoints.")
    parser.add_argument("--labels", type=Path, default=default_labels_path())
    parser.add_argument("--pdf-dir", type=Path, default=ROOT / "demos" / "referral_batch_large" / "pdfs")
    parser.add_argument("--user", default="sekretariat_kardiologie")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--sample-strategy", choices=["first", "random", "stratified"], default="stratified")
    parser.add_argument("--mode", choices=["fixture", "from-db", "live"], default="live")
    parser.add_argument(
        "--fixture",
        choices=["valid", "invalid", "truncated", "null-route", "multi-route", "unknown-alias"],
        default="valid",
    )
    parser.add_argument("--from-db", type=Path, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--csv-out", type=Path, default=None)
    parser.add_argument("--markdown-out", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "latest")
    parser.add_argument(
        "--debug-invalid",
        action="store_true",
        help="Write sanitized invalid rows under reports/debug.",
    )
    args = parser.parse_args()

    if args.labels == DEFAULT_METADATA_PATH and not DEFAULT_ADJUDICATED_LABELS_PATH.exists():
        print(
            "INFO: using synthetic source metadata labels. "
            "This fallback is for exploratory smoke checks only; the reported 500-PDF score uses "
            "demos/referral_batch_large/pdf_adjudicated_labels.csv.",
            file=sys.stderr,
        )
    rows = _sample_rows(_read_label_rows(args.labels), limit=args.limit, seed=args.seed, strategy=args.sample_strategy)
    if args.mode == "from-db":
        if args.from_db is None:
            raise SystemExit("--from-db is required with --mode from-db")
        predictions = _load_db_predictions(rows, args.from_db)
    elif args.mode == "live":
        _assert_live_runtime_ready()
        predictions = _run_live_predictions(
            rows,
            labels_path=args.labels,
            pdf_dir=args.pdf_dir,
            user_id=args.user,
        )
    else:
        fixture = args.fixture
        predictions = {
            _row_key(row) or str(index): _analysis_from_fixture(row, fixture)
            for index, row in enumerate(rows)
        }
    metrics = _metrics(rows, predictions, dataset=str(args.labels))
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    manifest = build_run_manifest(
        root=ROOT,
        dataset_path=args.labels,
        prompt_version=REFERRAL_PROMPT_VERSION,
        taxonomy_path=ROOT / "configs" / "routing_taxonomy.yml",
        sample_strategy=args.sample_strategy,
        sample_size=len(rows),
        seed=args.seed,
    )
    write_referral_report(metrics, args.output_dir, manifest)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.csv_out:
        args.csv_out.parent.mkdir(parents=True, exist_ok=True)
        shutil_source = args.output_dir / "predictions.csv"
        args.csv_out.write_text(shutil_source.read_text(encoding="utf-8"), encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(
            (args.output_dir / "validation_report.md").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    if args.debug_invalid:
        debug_dir = ROOT / "reports" / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        debug_rows = metrics.get("invalid_response_rows", [])
        (debug_dir / "invalid_responses.json").write_text(
            json.dumps(debug_rows, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
