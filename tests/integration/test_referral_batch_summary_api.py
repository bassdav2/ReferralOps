from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.db.models import Document, ReferralCase
from backend.app.main import app
from backend.app.referral.schemas import MissingItem, ReferralAnalysis, RoutingProposal
from backend.app.referral.statuses import (
    STATUS_REVIEW_CONFIRM,
    STATUS_REVIEW_CORRECT,
    STATUS_REVIEW_PREFIX,
    STATUS_WRITEBACK_SENT,
)


def _client() -> TestClient:
    return TestClient(app)


def _document(session, document_id: str, *, access_groups: list[str] | None = None) -> Document:
    document = Document(
        id=document_id,
        source_system="test_referrals",
        external_id=f"{document_id}.txt",
        title=f"{document_id} title",
        mime_type="text/plain",
        sha256=document_id[:1] * 64,
        storage_pointer=f"missing/{document_id}.txt",
        source_uri=f"missing/{document_id}.txt",
        access_groups=access_groups or ["referral_reviewers"],
        contains_patient_data=True,
        parse_status="parsed",
    )
    session.add(document)
    session.commit()
    return document


def _analysis(
    document_id: str,
    *,
    routing_target: str | None = "kardiologie",
    confidence: float = 0.82,
    review: bool = False,
    missing_count: int = 0,
) -> ReferralAnalysis:
    return ReferralAnalysis(
        document_id=document_id,
        routing_proposal=RoutingProposal(
            department="Kardiologie" if routing_target else None,
            routing_target=routing_target,
            confidence=confidence,
        ),
        missing_items=[
            MissingItem(field=f"field_{index}", reason="missing in demo", severity="recommended")
            for index in range(missing_count)
        ],
        evidence=[{"claim": "demo", "quote": "Zuweisung wegen Thoraxbeschwerden.", "page": 1}],
        human_review_required=review,
    )


def _case(
    session,
    case_id: str,
    document_id: str,
    *,
    status: str = "analysis_ready",
    analysis: ReferralAnalysis | None = None,
) -> ReferralCase:
    case = ReferralCase(
        id=case_id,
        document_id=document_id,
        status=status,
        analysis_json=(analysis or _analysis(document_id)).model_dump(mode="json"),
        model_profile="test_double",
        prompt_version="test",
        created_by="sekretariat_kardiologie",
    )
    session.add(case)
    session.commit()
    return case


def test_batch_summary_counts_new_analyzed_review_and_reviewed_statuses(session):
    _document(session, "summary-new")
    review_document = _document(session, "summary-review")
    confirmed_document = _document(session, "summary-confirmed")
    corrected_document = _document(session, "summary-corrected")
    rejected_document = _document(session, "summary-rejected")
    question_document = _document(session, "summary-question")
    forwarded_document = _document(session, "summary-forwarded")
    _case(session, "summary-review-case", review_document.id, analysis=_analysis(review_document.id, review=True))
    _case(session, "summary-confirmed-case", confirmed_document.id, status=STATUS_REVIEW_CONFIRM)
    _case(session, "summary-corrected-case", corrected_document.id, status=STATUS_REVIEW_CORRECT)
    _case(session, "summary-rejected-case", rejected_document.id, status=f"{STATUS_REVIEW_PREFIX}reject")
    _case(session, "summary-question-case", question_document.id, status=f"{STATUS_REVIEW_PREFIX}question")
    _case(session, "summary-forwarded-case", forwarded_document.id, status=STATUS_WRITEBACK_SENT)

    response = _client().get("/api/referrals/batch-summary", headers={"X-Demo-User": "sekretariat_kardiologie"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_documents"] == 7
    assert payload["active_worklist"] == 4
    assert payload["open_items"] == 2
    assert payload["new_documents"] == 1
    assert payload["analyzed"] == 6
    assert payload["review_required"] == 1
    assert payload["ready_to_forward"] == 2
    assert payload["forwarded"] == 1
    assert payload["confirmed"] == 1
    assert payload["corrected"] == 1
    assert payload["rejected"] == 1
    assert payload["questions"] == 1


def test_batch_summary_counts_routing_distribution_and_missing_fields(session):
    cardiology_document = _document(session, "summary-cardio")
    radiology_document = _document(session, "summary-radio")
    _case(
        session,
        "summary-cardio-case",
        cardiology_document.id,
        analysis=_analysis(cardiology_document.id, routing_target="kardiologie", missing_count=2),
    )
    _case(
        session,
        "summary-radio-case",
        radiology_document.id,
        analysis=_analysis(radiology_document.id, routing_target="radiologie", missing_count=1),
    )

    response = _client().get("/api/referrals/batch-summary", headers={"X-Demo-User": "sekretariat_kardiologie"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["routing_distribution"] == {"kardiologie": 1, "radiologie": 1}
    assert isinstance(payload["top_missing_fields"], list)
    assert payload["top_missing_fields"][0]["field"] == "field_0"
    assert payload["top_missing_fields"][0]["count"] == 2


def test_batch_summary_is_read_only_and_does_not_create_cases(session):
    _document(session, "summary-read-only-new")
    before_cases = session.query(ReferralCase).count()

    response = _client().get("/api/referrals/batch-summary", headers={"X-Demo-User": "sekretariat_kardiologie"})

    after_cases = session.query(ReferralCase).count()
    assert response.status_code == 200
    assert before_cases == after_cases
    payload = response.json()
    assert payload["total_documents"] >= payload["analyzed"]
    assert "routing_distribution" in payload
    assert isinstance(payload["top_missing_fields"], list)


def test_batch_summary_excludes_invisible_documents(session):
    visible_document = _document(session, "summary-visible")
    invisible_document = _document(session, "summary-invisible", access_groups=["hygiene"])
    _case(session, "summary-visible-case", visible_document.id)
    _case(session, "summary-invisible-case", invisible_document.id)

    response = _client().get("/api/referrals/batch-summary", headers={"X-Demo-User": "sekretariat_kardiologie"})

    assert response.status_code == 200
    assert response.json()["total_documents"] == 1
