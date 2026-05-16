from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.app.db.models import Document, ReferralCase
from backend.app.referral.pipeline_events import list_pipeline_events, record_pipeline_event
from backend.app.referral.schemas import ReferralAnalysis
from backend.app.security.auth import get_current_user


def _document(session, document_id: str, access_groups: list[str]) -> Document:
    document = Document(
        id=document_id,
        source_system="test_referrals",
        external_id=f"{document_id}.txt",
        title=f"{document_id}.txt",
        mime_type="text/plain",
        sha256=document_id[:1] * 64,
        storage_pointer=f"missing/{document_id}.txt",
        source_uri=f"missing/{document_id}.txt",
        access_groups=access_groups,
        contains_patient_data=True,
        parse_status="parsed",
    )
    session.add(document)
    session.commit()
    return document


def _case(session, case_id: str, document: Document) -> ReferralCase:
    case = ReferralCase(
        id=case_id,
        document_id=document.id,
        status="analysis_ready",
        analysis_json=ReferralAnalysis(document_id=document.id).model_dump(mode="json"),
        model_profile="test_double",
        prompt_version="test",
        created_by="sekretariat_kardiologie",
    )
    session.add(case)
    session.commit()
    return case


def test_referral_reviewer_can_list_pipeline_events(session):
    document = _document(session, "visible-doc", ["referral_reviewers"])
    record_pipeline_event(
        session,
        stage="ocr",
        status="ok",
        message="OCR confidence 0.92",
        document_id=document.id,
        commit=True,
    )

    events = list_pipeline_events(session, get_current_user("sekretariat_kardiologie"))

    assert [event.message for event in events] == ["OCR confidence 0.92"]


def test_restricted_user_cannot_list_pipeline_events(session):
    with pytest.raises(HTTPException) as exc:
        list_pipeline_events(session, get_current_user("restricted_user"))

    assert exc.value.status_code == 403


def test_filtered_pipeline_events_enforce_case_visibility(session):
    document = _document(session, "radiology-doc", ["radiologie"])
    case = _case(session, "radiology-case", document)
    record_pipeline_event(
        session,
        stage="worklist",
        status="completed",
        message="Available in review worklist",
        document_id=document.id,
        case_id=case.id,
        commit=True,
    )

    with pytest.raises(HTTPException) as exc:
        list_pipeline_events(session, get_current_user("sekretariat_kardiologie"), case_id=case.id)

    assert exc.value.status_code == 403
