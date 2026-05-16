from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "frontend" / "src" / "App.tsx"
STYLES = ROOT / "frontend" / "src" / "styles.css"
REFERRAL_PAGE = ROOT / "frontend" / "src" / "referral-review" / "ReferralReviewPage.tsx"
INBOX_PANEL = ROOT / "frontend" / "src" / "referral-review" / "ReferralInboxPipelinePanel.tsx"
LOCAL_MODEL_PANEL = ROOT / "frontend" / "src" / "referral-review" / "LocalModelPanel.tsx"


def test_inbox_processing_does_not_disable_review_actions() -> None:
    source = REFERRAL_PAGE.read_text(encoding="utf-8")

    assert "const [inboxBusyAction, setInboxBusyAction]" in source
    assert 'setInboxBusyAction("process-inbox")' in source
    assert "const actionDisabled = busyAction !== null || selectionLoading || isResetting;" in source
    assert '"process-inbox"' not in source.split("const worklistDisabled =", 1)[1].split(";", 1)[0]


def test_processing_poll_keeps_latest_selection() -> None:
    source = REFERRAL_PAGE.read_text(encoding="utf-8")

    assert "selectedDocumentIdRef.current = selectedDocumentId" in source
    assert 'if (inboxBusyAction !== "process-inbox") return;' in source
    assert "refreshQueue(selectedDocumentIdRef.current, \"active\", { showBusy: false })" in source


def test_reset_demo_button_remains_visible_but_admin_gated() -> None:
    source = INBOX_PANEL.read_text(encoding="utf-8")

    assert "const resetDisabled = disabled || processing || uploading || resetting || !canReset;" in source
    assert "Only IT/Admin Demo can reset the demo" in source
    assert "{canReset && (" not in source
    assert 'text(language, "Demo zuruecksetzen", "Reset demo")' in source


def test_dashboard_opens_as_it_admin_demo_user() -> None:
    source = APP.read_text(encoding="utf-8")

    assert 'useState<UserKey>("it_admin")' in source


def test_local_model_timeout_defaults_to_zero() -> None:
    source = LOCAL_MODEL_PANEL.read_text(encoding="utf-8")

    assert 'const [timeoutSeconds, setTimeoutSeconds] = useState("0");' in source
    assert 'config.timeout_seconds === null ? "0"' in source
    assert "timeout < 0" in source
    assert "min={0}" in source


def test_referral_dashboard_can_scroll_on_short_viewports() -> None:
    source = STYLES.read_text(encoding="utf-8")

    assert ".referral-module {\n  overflow: auto;" in source
    assert "scrollbar-gutter: stable;" in source
    assert "flex: 1 0 360px;" in source
    assert "min-height: 360px;" in source
    assert "flex-basis: 640px;" in source
    assert ".queue-pane,\n  .document-pane,\n  .analysis-pane {\n    min-height: 320px;" in source
