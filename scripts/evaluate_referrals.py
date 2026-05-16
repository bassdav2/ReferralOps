from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("APP_ENV", "demo")
os.environ.setdefault("DATABASE_URL", "sqlite:///./eval_hospital_ai.db")
os.environ.setdefault("MODEL_PROVIDER", "gemma_vllm")
os.environ.setdefault("EMBEDDING_PROVIDER", "lexical_only")
os.environ.setdefault("NO_EXTERNAL_AI_CALLS", "true")
os.environ.setdefault("GUIDELINE_EXTRACTIVE_MODE", "true")

from backend.app.evaluation.metrics_referrals import evaluate_demo_referrals, markdown_table
from backend.app.evaluation.reporting import build_run_manifest, write_referral_report
from backend.app.referral.prompts import REFERRAL_PROMPT_VERSION


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate synthetic referral routing and report artifacts.")
    parser.add_argument("--dataset", type=Path, default=ROOT / "demos" / "eval" / "referrals.yml")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--sample-strategy", choices=["first", "random", "stratified"], default="first")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "latest")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args()

    metrics = evaluate_demo_referrals(
        args.dataset,
        limit=args.limit,
        seed=args.seed,
        sample_strategy=args.sample_strategy,
    )
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    print()
    print(markdown_table(metrics))
    if not args.no_report:
        manifest = build_run_manifest(
            root=ROOT,
            dataset_path=args.dataset,
            prompt_version=REFERRAL_PROMPT_VERSION,
            taxonomy_path=ROOT / "configs" / "routing_taxonomy.yml",
            sample_strategy=args.sample_strategy,
            sample_size=metrics.get("sample_size"),
            seed=args.seed,
            run_id=args.run_id,
        )
        write_referral_report(metrics, args.output_dir, manifest)


if __name__ == "__main__":
    main()
