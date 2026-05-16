from __future__ import annotations

from pathlib import Path


def infer_title(path: Path) -> str:
    return path.stem.replace("_", " ").title()

