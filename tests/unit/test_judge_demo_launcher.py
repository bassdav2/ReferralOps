import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_judge_demo_launcher_is_executable_and_local_only() -> None:
    script = ROOT / "scripts" / "start_judge_demo.sh"
    content = script.read_text(encoding="utf-8")

    assert script.exists()
    assert os.access(script, os.X_OK)
    assert "NO_EXTERNAL_AI_CALLS=true" in content
    assert ".env.local-model.example" in content
    assert "Install missing system dependencies now?" in content
    assert "brew install" in content
    assert "python@3.12" in content
    assert "tesseract-lang" in content
    assert "npm --prefix frontend ci" in content
    assert 'install -e ".[dev]"' in content
    assert "scripts/ingest_guidelines.py" in content
    assert "backend.app.main:app" in content
    assert "http://127.0.0.1:5173" in content
    assert "http://127.0.0.1:8000" in content
    assert "BACKEND_CORS_ORIGINS" in content
    assert "http://localhost:$FRONTEND_PORT" in content
    assert "TESSERACT_CMD" in content
    assert "TESSDATA_PREFIX" in content
    assert "make bootstrap" not in content


def test_macos_command_wrapper_calls_judge_launcher() -> None:
    wrapper = ROOT / "Start ReferralOps.command"
    content = wrapper.read_text(encoding="utf-8")

    assert wrapper.exists()
    assert os.access(wrapper, os.X_OK)
    assert "scripts/start_judge_demo.sh" in content


def test_windows_command_wrapper_calls_powershell_launcher() -> None:
    wrapper = ROOT / "Start ReferralOps.cmd"
    content = wrapper.read_text(encoding="utf-8")

    assert wrapper.exists()
    assert "powershell.exe" in content
    assert "-ExecutionPolicy Bypass" in content
    assert "scripts\\start_judge_demo.ps1" in content


def test_windows_powershell_launcher_matches_judge_demo_flow() -> None:
    script = ROOT / "scripts" / "start_judge_demo.ps1"
    content = script.read_text(encoding="utf-8")

    assert script.exists()
    assert '$env:NO_EXTERNAL_AI_CALLS = "true"' in content
    assert ".env.local-model.example" in content
    assert "Install missing system dependencies with winget now?" in content
    assert "Python.Python.3.12" in content
    assert "OpenJS.NodeJS.LTS" in content
    assert "UB-Mannheim.TesseractOCR" in content
    assert "scripts/check_runtime.py" in content
    assert "scripts/ingest_guidelines.py" in content
    assert "backend.app.main:app" in content
    assert '"--prefix", "frontend", "run", "dev"' in content
    assert "http://127.0.0.1:5173" in content
    assert "http://127.0.0.1:8000" in content
    assert "BACKEND_CORS_ORIGINS" in content
    assert "http://localhost:$FrontendPort" in content
    assert "Set-TesseractEnvironment" in content
    assert "TESSERACT_CMD" in content
    assert "TESSDATA_PREFIX" in content


def test_readme_prioritizes_double_click_launchers() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert readme.index("Start ReferralOps.command") < readme.index("Manual system install")
    assert readme.index("Start ReferralOps.cmd") < readme.index("Manual system install")
    assert "winget install -e --id Python.Python.3.12" in readme
    assert "brew install python@3.12 node tesseract tesseract-lang" in readme
    assert "you do not need to run `npm install` manually" in readme
