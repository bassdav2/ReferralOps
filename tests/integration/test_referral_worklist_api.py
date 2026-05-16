from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from backend.app.db.models import Document, ReferralCase
from backend.app.main import app
from backend.app.referral.schemas import MissingItem, ReferralAnalysis, RoutingProposal
from backend.app.referral.statuses import STATUS_ANALYSIS_READY, STATUS_REVIEW_CONFIRM, STATUS_WRITEBACK_SENT


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
    ocr_status: str = "unknown",
    warnings: list[str] | None = None,
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
        ocr_status=ocr_status,
        ocr_min_confidence=0.41 if ocr_status in {"low", "failed"} else None,
        warnings=warnings or [],
    )


def _case(
    session,
    case_id: str,
    document_id: str,
    *,
    created_at: datetime | None = None,
    status: str = STATUS_ANALYSIS_READY,
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
        created_at=created_at or datetime(2026, 1, 1, tzinfo=UTC),
    )
    session.add(case)
    session.commit()
    return case


def test_worklist_includes_new_documents_and_analyzed_cases(session):
    new_document = _document(session, "new-document")
    analyzed_document = _document(session, "analyzed-document")
    case = _case(session, "case-analyzed", analyzed_document.id)

    response = _client().get("/api/referrals/cases", headers={"X-Demo-User": "sekretariat_kardiologie"})

    assert response.status_code == 200
    payload = response.json()
    by_document = {item["document_id"]: item for item in payload}
    assert by_document[new_document.id]["status"] == "new"
    assert by_document[new_document.id]["case_id"] is None
    assert by_document[analyzed_document.id]["case_id"] == case.id
    assert set(by_document[analyzed_document.id]) >= {
        "case_id",
        "document_id",
        "document_title",
        "status",
        "routing_target",
        "confidence",
        "human_review_required",
        "missing_count",
        "ocr_min_confidence",
        "ocr_status",
        "warnings",
        "created_at",
    }


def test_worklist_uses_latest_case_per_document(session):
    document = _document(session, "latest-document")
    _case(session, "old-case", document.id, created_at=datetime(2026, 1, 1, tzinfo=UTC))
    latest = _case(
        session,
        "latest-case",
        document.id,
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        analysis=_analysis(document.id, routing_target="radiologie", confidence=0.9),
    )

    response = _client().get("/api/referrals/cases", headers={"X-Demo-User": "sekretariat_kardiologie"})

    assert response.status_code == 200
    item = response.json()[0]
    assert item["case_id"] == latest.id
    assert item["routing_target"] == "radiologie"


def test_worklist_filter_review_required(session):
    review_document = _document(session, "review-document")
    ok_document = _document(session, "ok-document")
    _case(session, "review-case", review_document.id, analysis=_analysis(review_document.id, review=True))
    _case(session, "ok-case", ok_document.id, analysis=_analysis(ok_document.id, review=False))

    response = _client().get(
        "/api/referrals/cases?filter=review_required",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
    )

    assert response.status_code == 200
    assert [item["document_id"] for item in response.json()] == [review_document.id]


def test_worklist_filter_ocr_low(session):
    low_document = _document(session, "ocr-low-document")
    failed_document = _document(session, "ocr-failed-document")
    ok_document = _document(session, "ocr-ok-document")
    _case(session, "ocr-low-case", low_document.id, analysis=_analysis(low_document.id, ocr_status="low"))
    _case(session, "ocr-failed-case", failed_document.id, analysis=_analysis(failed_document.id, ocr_status="failed"))
    _case(session, "ocr-ok-case", ok_document.id, analysis=_analysis(ok_document.id, ocr_status="ok"))

    response = _client().get(
        "/api/referrals/cases?filter=ocr_low",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
    )

    assert response.status_code == 200
    assert {item["document_id"] for item in response.json()} == {low_document.id, failed_document.id}


def test_worklist_filter_route_unclear(session):
    unclear_document = _document(session, "unclear-route-document")
    clear_document = _document(session, "clear-route-document")
    _case(
        session,
        "unclear-route-case",
        unclear_document.id,
        analysis=_analysis(unclear_document.id, routing_target=None, confidence=0.3),
    )
    _case(session, "clear-route-case", clear_document.id, analysis=_analysis(clear_document.id, confidence=0.9))

    response = _client().get(
        "/api/referrals/cases?filter=route_unclear",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
    )

    assert response.status_code == 200
    assert [item["document_id"] for item in response.json()] == [unclear_document.id]


def test_worklist_excludes_restricted_user(session):
    _document(session, "restricted-hidden-document")

    restricted = _client().get("/api/referrals/cases", headers={"X-Demo-User": "restricted_user"})

    assert restricted.status_code in {401, 403}


def test_worklist_filter_confirmed(session):
    confirmed_document = _document(session, "confirmed-document")
    new_document = _document(session, "confirmed-filter-new-document")
    _case(session, "confirmed-case", confirmed_document.id, status=STATUS_REVIEW_CONFIRM)

    response = _client().get(
        "/api/referrals/cases?filter=confirmed",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
    )

    assert response.status_code == 200
    assert [item["document_id"] for item in response.json()] == [confirmed_document.id]
    assert new_document.id not in {item["document_id"] for item in response.json()}


def test_worklist_active_keeps_confirmed_until_writeback_sent(session):
    confirmed_document = _document(session, "active-confirmed-document")
    sent_document = _document(session, "active-sent-document")
    _case(session, "active-confirmed-case", confirmed_document.id, status=STATUS_REVIEW_CONFIRM)
    _case(session, "active-sent-case", sent_document.id, status=STATUS_WRITEBACK_SENT)

    response = _client().get(
        "/api/referrals/cases?filter=active",
        headers={"X-Demo-User": "sekretariat_kardiologie"},
    )

    assert response.status_code == 200
    document_ids = {item["document_id"] for item in response.json()}
    assert confirmed_document.id in document_ids
    assert sent_document.id not in document_ids
