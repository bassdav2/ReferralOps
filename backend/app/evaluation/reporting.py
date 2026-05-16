from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class RunManifest(BaseModel):
    run_id: str
    generated_at_utc: str
    evaluator_version: str = "referral-evaluator-v2"
    prompt_version: str
    taxonomy_hash: str | None
    git_commit: str | None
    git_dirty: bool
    model_provider: str
    model_id: str
    endpoint_type: str
    generation_max_tokens: int | None
    max_referral_text_chars: int | None
    dataset_path: str
    dataset_sha256: str | None
    sample_strategy: str
    sample_size: int | None
    seed: int | None
    python_version: str = Field(default_factory=platform.python_version)
    command: list[str] = Field(default_factory=list)
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    disclaimer: str = (
        "Synthetic administrative evaluation only. Not clinical validation, not autonomous triage, "
        "and not evidence for production patient-data use."
    )


def sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_output(root: Path, args: list[str]) -> str | None:
    try:
        return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def _git_commit(root: Path) -> str | None:
    return _git_output(root, ["rev-parse", "HEAD"])


def _git_dirty(root: Path) -> bool:
    status = _git_output(root, ["status", "--short"])
    return bool(status)


def build_run_manifest(
    *,
    root: Path,
    dataset_path: Path,
    prompt_version: str,
    taxonomy_path: Path,
    sample_strategy: str,
    sample_size: int | None,
    seed: int | None,
    run_id: str | None = None,
) -> RunManifest:
    now = datetime.now(UTC)
    provider = os.getenv("MODEL_PROVIDER", "test_double")
    endpoint_type = "test_double" if provider == "test_double" else "local_openai_compatible"
    return RunManifest(
        run_id=run_id or now.strftime("%Y%m%dT%H%M%SZ"),
        generated_at_utc=now.isoformat(),
        prompt_version=prompt_version,
        taxonomy_hash=sha256_file(taxonomy_path),
        git_commit=_git_commit(root),
        git_dirty=_git_dirty(root),
        model_provider=provider,
        model_id=os.getenv("GENERATION_MODEL_ID", "test-double"),
        endpoint_type=endpoint_type,
        generation_max_tokens=_safe_int(os.getenv("GENERATION_MAX_TOKENS")),
        max_referral_text_chars=_safe_int(os.getenv("MAX_REFERRAL_TEXT_CHARS")),
        dataset_path=str(dataset_path),
        dataset_sha256=sha256_file(dataset_path),
        sample_strategy=sample_strategy,
        sample_size=sample_size,
        seed=seed,
        command=sys.argv,
    )


def _safe_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _prediction_rows(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in metrics.get("case_results", []):
        actual = result.get("actual") or {}
        expected = result.get("expected") or {}
        rows.append(
            {
                "case_id": result.get("id"),
                "passed": result.get("passed"),
                "expected_route": expected.get("routing_target"),
                "predicted_route": actual.get("routing_target"),
                "top3_routes": actual.get("routing_candidates_top3", []),
                "model_output_valid": actual.get("model_output_valid"),
                "safe_fallback": actual.get("safe_fallback"),
                "human_review_required_expected": expected.get("human_review_required"),
                "human_review_required_predicted": actual.get("human_review_required"),
                "ocr_slice": actual.get("ocr_slice"),
                "errors": result.get("errors", []),
            }
        )
    return rows


def _markdown_report(metrics: dict[str, Any], manifest: RunManifest) -> str:
    rows = [
        ("Dataset", metrics.get("dataset")),
        ("Cases", metrics.get("cases")),
        ("Schema valid rate", metrics.get("schema_valid_rate")),
        ("Invalid model responses", metrics.get("model_response_invalid_count")),
        ("Routing top-1 exact accuracy", metrics.get("routing_top1_exact_accuracy")),
        ("Routing top-3 accuracy", metrics.get("routing_top3_accuracy")),
        ("Null/unknown route rate", metrics.get("null_unknown_route_rate")),
        ("Safe fallback rate", metrics.get("safe_fallback_rate")),
        ("Human review accuracy", metrics.get("human_review_accuracy")),
        ("Critical errors", metrics.get("critical_errors")),
    ]
    table = "\n".join(f"| {name} | {value} |" for name, value in rows)
    return (
        "# ReferralOps Validation Report\n\n"
        f"Run ID: `{manifest.run_id}`\n\n"
        "Synthetic administrative evaluation only. This is not clinical validation and does not support "
        "autonomous diagnosis, treatment, or triage claims.\n\n"
        "## Summary\n\n"
        "| Metric | Value |\n|---|---:|\n"
        f"{table}\n\n"
        "## Artifacts\n\n"
        "- `metrics.json`\n"
        "- `predictions.csv`\n"
        "- `per_route_metrics.csv`\n"
        "- `confusion_matrix.csv`\n"
        "- `invalid_responses.csv`\n"
        "- `ocr_slice_metrics.csv`\n"
        "- `run_manifest.json`\n\n"
        "## Charts\n\n"
        "![Routing by route](charts/routing_top1_by_route.svg)\n\n"
        "![Confusion matrix](charts/confusion_matrix.svg)\n\n"
        "![OCR slices](charts/ocr_slice_metrics.svg)\n\n"
        "![Schema validity](charts/schema_validity.svg)\n"
    )


def _bar_svg(title: str, rows: list[tuple[str, float | None]], *, width: int = 760, height: int = 300) -> str:
    margin_left = 190
    margin_right = 30
    bar_height = 24
    gap = 12
    chart_height = max(height, 70 + len(rows) * (bar_height + gap))
    inner_width = width - margin_left - margin_right
    body: list[str] = []
    for index, (label, value) in enumerate(rows):
        y = 50 + index * (bar_height + gap)
        score = 0.0 if value is None else max(0.0, min(1.0, float(value)))
        bar_width = int(inner_width * score)
        body.append(
            f'<text x="12" y="{y + 17}" font-size="13">{html.escape(str(label))}</text>'
            f'<rect x="{margin_left}" y="{y}" width="{inner_width}" height="{bar_height}" fill="#eef2f7"/>'
            f'<rect x="{margin_left}" y="{y}" width="{bar_width}" height="{bar_height}" fill="#2463eb"/>'
            f'<text x="{margin_left + inner_width + 8}" y="{y + 17}" font-size="13">{score:.2f}</text>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{chart_height}" '
        f'viewBox="0 0 {width} {chart_height}">'
        '<rect width="100%" height="100%" fill="white"/>'
        f'<text x="12" y="26" font-size="18" font-weight="700">{html.escape(title)}</text>'
        f"{''.join(body)}</svg>\n"
    )


def _confusion_svg(rows: list[dict[str, Any]], *, cell: int = 54) -> str:
    labels = sorted({row["expected_route"] for row in rows} | {row["actual_route"] for row in rows})
    if not labels:
        labels = ["no_data"]
    counts = {(row["expected_route"], row["actual_route"]): int(row["count"]) for row in rows}
    max_count = max(counts.values(), default=1)
    margin = 150
    width = margin + cell * len(labels) + 20
    height = margin + cell * len(labels) + 20
    body: list[str] = []
    for col, label in enumerate(labels):
        x = margin + col * cell
        body.append(
            f'<text x="{x + 6}" y="118" font-size="11" '
            f'transform="rotate(-35 {x + 6},118)">{html.escape(label)}</text>'
        )
    for row_index, expected in enumerate(labels):
        y = margin + row_index * cell
        body.append(f'<text x="12" y="{y + 31}" font-size="11">{html.escape(expected)}</text>')
        for col, actual in enumerate(labels):
            x = margin + col * cell
            count = counts.get((expected, actual), 0)
            opacity = 0.12 + 0.78 * (count / max_count if max_count else 0)
            body.append(
                f'<rect x="{x}" y="{y}" width="{cell - 2}" height="{cell - 2}" '
                f'fill="#2463eb" opacity="{opacity:.2f}"/>'
                f'<text x="{x + cell / 2 - 5}" y="{y + cell / 2 + 4}" font-size="13">{count}</text>'
            )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        '<rect width="100%" height="100%" fill="white"/>'
        '<text x="12" y="26" font-size="18" font-weight="700">Per-route confusion matrix</text>'
        '<text x="150" y="54" font-size="12">Actual route</text>'
        '<text x="12" y="140" font-size="12">Expected route</text>'
        f"{''.join(body)}</svg>\n"
    )


def write_referral_report(metrics: dict[str, Any], output_dir: Path, manifest: RunManifest) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    charts_dir = output_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    artifacts: dict[str, Path] = {
        "metrics": output_dir / "metrics.json",
        "predictions": output_dir / "predictions.csv",
        "per_route_metrics": output_dir / "per_route_metrics.csv",
        "confusion_matrix": output_dir / "confusion_matrix.csv",
        "invalid_responses": output_dir / "invalid_responses.csv",
        "ocr_slice_metrics": output_dir / "ocr_slice_metrics.csv",
        "validation_report": output_dir / "validation_report.md",
        "routing_top1_chart": charts_dir / "routing_top1_by_route.svg",
        "confusion_chart": charts_dir / "confusion_matrix.svg",
        "ocr_slice_chart": charts_dir / "ocr_slice_metrics.svg",
        "schema_validity_chart": charts_dir / "schema_validity.svg",
        "manifest": output_dir / "run_manifest.json",
    }

    _write_json(artifacts["metrics"], metrics)
    _write_csv(
        artifacts["predictions"],
        _prediction_rows(metrics),
        [
            "case_id",
            "passed",
            "expected_route",
            "predicted_route",
            "top3_routes",
            "model_output_valid",
            "safe_fallback",
            "human_review_required_expected",
            "human_review_required_predicted",
            "ocr_slice",
            "errors",
        ],
    )
    _write_csv(
        artifacts["per_route_metrics"],
        metrics.get("per_route_metrics", []),
        ["route", "support", "true_positive", "false_positive", "false_negative", "precision", "recall", "f1"],
    )
    _write_csv(
        artifacts["confusion_matrix"],
        metrics.get("confusion_matrix", []),
        ["expected_route", "actual_route", "count"],
    )
    _write_csv(
        artifacts["invalid_responses"],
        metrics.get("invalid_response_rows", []),
        ["case_id", "warnings", "invalid_reasons"],
    )
    _write_csv(
        artifacts["ocr_slice_metrics"],
        metrics.get("ocr_slice_metrics", []),
        [
            "slice",
            "cases",
            "routing_top1_correct",
            "routing_top1_accuracy",
            "schema_valid",
            "schema_valid_rate",
            "critical_errors",
        ],
    )
    artifacts["validation_report"].write_text(_markdown_report(metrics, manifest), encoding="utf-8")
    artifacts["routing_top1_chart"].write_text(
        _bar_svg(
            "Routing top-1 by route",
            [(row["route"], row.get("recall")) for row in metrics.get("per_route_metrics", [])],
        ),
        encoding="utf-8",
    )
    artifacts["confusion_chart"].write_text(_confusion_svg(metrics.get("confusion_matrix", [])), encoding="utf-8")
    artifacts["ocr_slice_chart"].write_text(
        _bar_svg(
            "OCR slice routing accuracy",
            [(row["slice"], row.get("routing_top1_accuracy")) for row in metrics.get("ocr_slice_metrics", [])],
        ),
        encoding="utf-8",
    )
    artifacts["schema_validity_chart"].write_text(
        _bar_svg(
            "Model response schema validity",
            [
                ("schema_valid_rate", metrics.get("schema_valid_rate")),
                ("safe_fallback_rate", metrics.get("safe_fallback_rate")),
                ("null_unknown_route_rate", metrics.get("null_unknown_route_rate")),
            ],
        ),
        encoding="utf-8",
    )

    manifest.artifact_hashes = {}
    for key, path in artifacts.items():
        if key != "manifest":
            manifest.artifact_hashes[str(path.relative_to(output_dir))] = sha256_file(path) or ""
    _write_json(artifacts["manifest"], manifest.model_dump(mode="json"))
    return artifacts
