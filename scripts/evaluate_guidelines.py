from __future__ import annotations

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

from backend.app.evaluation.metrics_rag import evaluate_demo_guidelines, markdown_table


def main() -> None:
    metrics = evaluate_demo_guidelines()
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    print()
    print(markdown_table(metrics))


if __name__ == "__main__":
    main()
