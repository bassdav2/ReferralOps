from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.db.models import Document, ReferralCase, ReferralReview
from backend.app.referral.demo_outputs import (
    ensure_demo_output_folders,
    output_folder_for_decision,
    write_review_demo_output,
)
from backend.app.referral.schemas import MissingItem, ReferralAnalysis, RoutingProposal
from backend.app.security.auth import get_current_user


@pytest.fixture
def demo_output_dir(tmp_path: Path, monkeypatch, reset_runtime_caches):
    output_dir = tmp_path / "demo_outputs" / "referrals"
    monkeypatch.setenv("REFERRAL_DEMO_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("DEMO_OUTPUTS_ENABLED", "true")
    reset_runtime_caches()
    yield output_dir
    reset_runtime_caches()


def _case_and_review(session, decision: str = "confirm") -> tuple[ReferralCase, ReferralReview]:
    document = Document(
        id="demo-output-doc",
        source_system="test_referrals",
        external_id="/tmp/demo-output.pdf",
        title="demo output",
        mime_type="application/pdf",
        sha256="b" * 64,
        storage_pointer="/tmp/demo-output.pdf",
        source_uri="/tmp/demo-output.pdf",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
        parse_status="parsed",
    )
    analysis = ReferralAnalysis(
        document_id=document.id,
        routing_proposal=RoutingProposal(
            department="Kardiologie",
            routing_target="kardiologie",
            confidence=0.9,
        ),
        missing_items=[
            MissingItem(field="patient.phone", reason="missing", severity="blocking"),
        ],
        human_review_required=True,
    )
    case = ReferralCase(
        id="demo-output-case",
        document_id=document.id,
        status=f"review_{decision}",
        analysis_json=analysis.model_dump(mode="json"),
        model_profile="google/gemma-4-E4B-it",
        prompt_version="test-prompt",
        created_by="sekretariat_kardiologie",
    )
    review = ReferralReview(
        id=f"review-{decision}",
        case_id=case.id,
        reviewer_id="sekretariat_kardiologie",
        decision=decision,
        comment="Demo comment",
    )
    session.add_all([document, case, review])
    session.flush()
    return case, review


def test_output_folder_for_decision_maps_all_decisions():
    assert output_folder_for_decision("confirm") == "confirmed"
    assert output_folder_for_decision("correct") == "corrected"
    assert output_folder_for_decision("question") == "questions"
    assert output_folder_for_decision("reject") == "rejected"


def test_demo_output_folders_include_all_routing_targets(demo_output_dir: Path):
    ensure_demo_output_folders()

    assert (demo_output_dir / "departments" / "kardiologie").is_dir()
    assert (demo_output_dir / "departments" / "innere_medizin").is_dir()
    assert (demo_output_dir / "departments" / "radiologie").is_dir()
    assert (demo_output_dir / "departments" / "notfall").is_dir()


def test_review_output_json_contains_required_demo_fields(session, demo_output_dir: Path):
    case, review = _case_and_review(session)

    result = write_review_demo_output(
        session,
        case=case,
        review=review,
        user=get_current_user("sekretariat_kardiologie"),
        comment="Demo comment",
    )

    assert result.written is True
    payload = json.loads((demo_output_dir / result.relative_path).read_text(encoding="utf-8"))
    assert payload["case_id"] == case.id
    assert payload["document_id"] == case.document_id
    assert payload["decision"] == "confirm"
    assert payload["decision_label"] == "Freigeben"
    assert payload["routing_target"] == "kardiologie"
    assert payload["model_confidence"] == 0.9
    assert payload["missing_fields"] == ["patient.phone"]
    assert payload["source_pdf"] == "demo-output.pdf"
    assert payload["model_profile"] == "google/gemma-4-E4B-it"
    assert payload["prompt_version"] == "test-prompt"
    assert payload["comment"] == "Demo comment"


def test_review_output_json_does_not_contain_full_text_or_prompt(session, demo_output_dir: Path):
    case, review = _case_and_review(session)

    result = write_review_demo_output(
        session,
        case=case,
        review=review,
        user=get_current_user("sekretariat_kardiologie"),
        comment=None,
    )

    raw = (demo_output_dir / result.relative_path).read_text(encoding="utf-8")
    assert "Zuweisung wegen Thoraxbeschwerden" not in raw
    assert "REFERRAL_SYSTEM_PROMPT" not in raw
    assert "raw_model_output" not in raw
