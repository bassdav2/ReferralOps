from __future__ import annotations

from pathlib import Path

from backend.app.db.models import AuditEvent, Document, DocumentPage
from backend.app.documents.registry import register_file
from backend.app.referral.review import review_referral_case
from backend.app.referral.schemas import ReviewRequest
from backend.app.referral.service import analyze_referral
from backend.app.security.auth import get_current_user


def _missing_document(session, document_id: str) -> Document:
    document = Document(
        id=document_id,
        source_system="manual",
        external_id=f"{document_id}.pdf",
        title=document_id,
        mime_type="application/pdf",
        sha256=document_id[:1] * 64,
        storage_pointer=f"missing/{document_id}.pdf",
        source_uri=f"missing/{document_id}.pdf",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
        parse_status="pending",
    )
    session.add(document)
    session.commit()
    return document


def test_referral_analysis_review_and_audit(session, tmp_path: Path):
    sample = tmp_path / "referral.txt"
    sample.write_text(
        "Zuweisung wegen Thoraxbeschwerden und Dyspnoe. Medikamentenliste fehlt.",
        encoding="utf-8",
    )
    user = get_current_user("sekretariat_kardiologie")
    document = register_file(
        session,
        sample,
        title="synthetic cardiology referral",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
    )
    case = analyze_referral(session, document.id, user)
    assert case.analysis.routing_proposal.routing_target == "kardiologie"
    assert any(item.field == "attachments.medication_list" for item in case.analysis.missing_items)
    assert case.analysis.evidence

    review = review_referral_case(session, case.id, user, ReviewRequest(decision="confirm"))
    assert review.case_id == case.id

    events = session.query(AuditEvent).all()
    assert {event.action for event in events} >= {"referral.model_suggestion", "referral.review"}


def test_referral_analysis_returns_schema_valid_json_with_evidence(session, tmp_path: Path):
    sample = tmp_path / "schema_valid_referral.txt"
    sample.write_text("Zuweisung wegen Thoraxbeschwerden und Dyspnoe. Medikamentenliste fehlt.", encoding="utf-8")
    user = get_current_user("sekretariat_kardiologie")
    document = register_file(
        session,
        sample,
        title="schema valid referral",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
    )

    case = analyze_referral(session, document.id, user)

    assert case.analysis.document_id == document.id
    assert case.analysis.evidence
    assert case.analysis.model_dump(mode="json")


def test_recommended_missing_item_does_not_force_human_review_when_evidence_is_present(session, tmp_path: Path):
    sample = tmp_path / "review_required_referral.txt"
    sample.write_text("Zuweisung wegen Thoraxbeschwerden und Dyspnoe. Medikamentenliste fehlt.", encoding="utf-8")
    user = get_current_user("sekretariat_kardiologie")
    document = register_file(
        session,
        sample,
        title="review required referral",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
    )

    case = analyze_referral(session, document.id, user)

    assert any(item.severity == "recommended" for item in case.analysis.missing_items)
    assert case.analysis.evidence
    assert case.analysis.human_review_required is False


def test_low_ocr_confidence_forces_human_review_and_warning(session):
    user = get_current_user("sekretariat_kardiologie")
    document = _missing_document(session, "low-ocr-document")
    session.add(
        DocumentPage(
            document_id=document.id,
            page_number=1,
            text="Zuweisung wegen Thoraxbeschwerden und Dyspnoe.",
            ocr_confidence=0.42,
        )
    )
    session.commit()

    case = analyze_referral(session, document.id, user)

    assert case.analysis.human_review_required is True
    assert case.analysis.ocr_status == "low"
    assert case.analysis.ocr_min_confidence == 0.42
    assert "Low OCR confidence" in " ".join(case.analysis.warnings)


def test_unknown_ocr_confidence_does_not_add_low_ocr_warning(session):
    user = get_current_user("sekretariat_kardiologie")
    document = _missing_document(session, "unknown-ocr-document")
    session.add(
        DocumentPage(
            document_id=document.id,
            page_number=1,
            text="Zuweisung wegen Thoraxbeschwerden und Dyspnoe.",
            ocr_confidence=None,
        )
    )
    session.commit()

    case = analyze_referral(session, document.id, user)

    assert case.analysis.ocr_status == "unknown"
    assert case.analysis.ocr_min_confidence is None
    assert "Low OCR confidence" not in " ".join(case.analysis.warnings)


def test_missing_or_unparseable_document_sets_ocr_review_warning(session):
    user = get_current_user("sekretariat_kardiologie")
    document = _missing_document(session, "missing-unparseable-document")

    case = analyze_referral(session, document.id, user)

    assert case.analysis.human_review_required is True
    assert case.analysis.ocr_status == "failed"
    assert any("OCR" in warning for warning in case.analysis.warnings)


def test_review_confirm_updates_status_and_audit_log(session, tmp_path: Path):
    sample = tmp_path / "confirm_referral.txt"
    sample.write_text("Zuweisung wegen Thoraxbeschwerden und Dyspnoe.", encoding="utf-8")
    user = get_current_user("sekretariat_kardiologie")
    document = register_file(
        session,
        sample,
        title="confirm referral",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
    )
    case = analyze_referral(session, document.id, user)

    review = review_referral_case(session, case.id, user, ReviewRequest(decision="confirm"))

    assert review.decision == "confirm"
    assert session.query(AuditEvent).filter(AuditEvent.action == "referral.review").count() == 1


def test_review_modify_requires_valid_correction_payload():
    from pydantic import ValidationError

    try:
        ReviewRequest(decision="correct")
    except ValidationError as exc:
        assert "corrected_analysis is required" in str(exc)
    else:
        raise AssertionError("decision=correct without corrected_analysis must fail")
