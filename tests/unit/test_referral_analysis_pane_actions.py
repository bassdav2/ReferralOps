from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_PANE = ROOT / "frontend" / "src" / "referral-review" / "ReferralAnalysisPane.tsx"
REVIEW_PAGE = ROOT / "frontend" / "src" / "referral-review" / "ReferralReviewPage.tsx"


def test_pending_auto_analysis_has_no_manual_analyze_button() -> None:
    source = ANALYSIS_PANE.read_text(encoding="utf-8")

    assert 'text(language, "Analysieren", "Analyze")' not in source
    assert "Analysis running or queued" in source
    assert "The PDF inbox analyzes this document automatically" in source


def test_completed_analysis_exposes_explicit_reanalyze_action() -> None:
    source = ANALYSIS_PANE.read_text(encoding="utf-8")

    assert 'title={text(language, "Erneut analysieren", "Reanalyze")}' in source
    assert 'onClick={onAnalyze}' in source
    assert 'renderIcon={Document}' in source


def test_review_required_status_is_red() -> None:
    source = ANALYSIS_PANE.read_text(encoding="utf-8")

    assert 'type={analysis.human_review_required ? "red" : "green"}' in source
    assert "Review required" in source


def test_reanalyze_has_its_own_disabled_state() -> None:
    analysis_source = ANALYSIS_PANE.read_text(encoding="utf-8")
    page_source = REVIEW_PAGE.read_text(encoding="utf-8")

    assert "reanalyzeDisabled: boolean;" in analysis_source
    assert "disabled={reanalyzeDisabled}" in analysis_source
    assert "const [reanalyzingDocumentId, setReanalyzingDocumentId]" in page_source
    assert 'setBusyAction("analyze")' not in page_source
    assert "reanalyzeDisabled={reanalyzeDisabled}" in page_source


def test_writeback_button_is_limited_to_reviewed_statuses() -> None:
    source = ANALYSIS_PANE.read_text(encoding="utf-8")

    assert 'new Set(["review_confirm", "review_correct"])' in source
    assert "disabled={disabled || !writebackAllowed}" in source
