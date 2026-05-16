from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from backend.app.core.config import get_settings
from scripts.local_model_smoke import main

ROOT = Path(__file__).resolve().parents[2]


def test_local_model_smoke_script_exists():
    assert (ROOT / "scripts" / "local_model_smoke.py").exists()


def test_smoke_local_model_alias_runs_directly_without_import_error(monkeypatch):
    monkeypatch.delenv("RUN_REAL_LOCAL_MODEL_SMOKE", raising=False)

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "smoke_local_model.py")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Set RUN_REAL_LOCAL_MODEL_SMOKE=1" in output
    assert "ModuleNotFoundError" not in output


def test_local_model_smoke_script_has_clear_missing_config_error(monkeypatch):
    monkeypatch.setenv("RUN_REAL_LOCAL_MODEL_SMOKE", "1")
    monkeypatch.setenv("MODEL_PROVIDER", "test_double")
    get_settings.cache_clear()

    with pytest.raises(SystemExit, match="MODEL_PROVIDER must be gemma_vllm"):
        main()


def test_real_local_model_smoke_skips_without_RUN_REAL_LOCAL_MODEL_SMOKE(monkeypatch):
    monkeypatch.delenv("RUN_REAL_LOCAL_MODEL_SMOKE", raising=False)
    monkeypatch.setenv("MODEL_PROVIDER", "gemma_vllm")
    get_settings.cache_clear()

    with pytest.raises(SystemExit, match="Set RUN_REAL_LOCAL_MODEL_SMOKE=1"):
        main()
