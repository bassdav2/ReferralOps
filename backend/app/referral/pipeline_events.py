from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.core.errors import not_found
from backend.app.db.models import Document, ReferralCase, ReferralPipelineEvent
from backend.app.referral.schemas import ReferralPipelineEventRead
from backend.app.referral.statuses import PIPELINE_STAGES, PIPELINE_STATUSES
from backend.app.security.acl import (
    has_group_overlap,
    is_admin,
    require_referral_case_visible,
    require_referral_reviewer,
    require_visible,
)
from backend.app.security.auth import DemoUser

MAX_PIPELINE_PAYLOAD_BYTES = 4096


def _small_json_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    try:
        serialized = json.dumps(payload, default=str, ensure_ascii=True, sort_keys=True)
    except TypeError:
        return {"serialization_warning": "payload was not JSON serializable"}
    if len(serialized.encode("utf-8")) <= MAX_PIPELINE_PAYLOAD_BYTES:
        return json.loads(serialized)
    return {
        "truncated": True,
        "keys": sorted(str(key) for key in payload.keys())[:20],
    }


def record_pipeline_event(
    session: Session,
    *,
    stage: str,
    status: str,
    message: str,
    document_id: str | None = None,
    case_id: str | None = None,
    payload: dict[str, Any] | None = None,
    commit: bool = False,
) -> ReferralPipelineEvent:
    if stage not in PIPELINE_STAGES:
        raise ValueError(f"Unsupported referral pipeline stage: {stage}")
    if status not in PIPELINE_STATUSES:
        raise ValueError(f"Unsupported referral pipeline status: {status}")

    event = ReferralPipelineEvent(
        id=uuid.uuid4().hex,
        document_id=document_id,
        case_id=case_id,
        stage=stage,
        status=status,
        message=message,
        payload_json=_small_json_payload(payload),
    )
    session.add(event)
    session.flush()
    if commit:
        session.commit()
        session.refresh(event)
    return event


def event_to_read(event: ReferralPipelineEvent) -> ReferralPipelineEventRead:
    return ReferralPipelineEventRead(
        id=event.id,
        document_id=event.document_id,
        case_id=event.case_id,
        stage=event.stage,
        status=event.status,
        message=event.message,
        payload=event.payload_json,
        created_at=event.created_at,
    )


def _visible_document_ids(session: Session, user: DemoUser) -> set[str]:
    documents = session.query(Document.id, Document.access_groups).all()
    if is_admin(user):
        return {document_id for document_id, access_groups in documents if access_groups}
    return {document_id for document_id, access_groups in documents if has_group_overlap(user, access_groups)}


def _visible_case_ids(session: Session, visible_document_ids: set[str]) -> set[str]:
    if not visible_document_ids:
        return set()
    cases = session.query(ReferralCase.id).filter(ReferralCase.document_id.in_(visible_document_ids)).all()
    return {case_id for (case_id,) in cases}


def _require_document_visible(session: Session, document_id: str, user: DemoUser) -> None:
    document = session.get(Document, document_id)
    if not document:
        raise not_found("Document not found")
    if is_admin(user):
        return
    require_visible(user, document.access_groups)


def list_pipeline_events(
    session: Session,
    user: DemoUser,
    *,
    limit: int = 100,
    document_id: str | None = None,
    case_id: str | None = None,
) -> list[ReferralPipelineEventRead]:
    require_referral_reviewer(user)
    bounded_limit = max(1, min(limit, 500))

    if document_id:
        _require_document_visible(session, document_id, user)
    if case_id:
        if not is_admin(user):
            require_referral_case_visible(session, case_id, user)

    visible_document_ids = _visible_document_ids(session, user)
    visible_case_ids = _visible_case_ids(session, visible_document_ids)

    query = session.query(ReferralPipelineEvent)
    if document_id:
        query = query.filter(ReferralPipelineEvent.document_id == document_id)
    if case_id:
        query = query.filter(ReferralPipelineEvent.case_id == case_id)

    query = query.filter(
        or_(
            ReferralPipelineEvent.document_id.is_(None),
            ReferralPipelineEvent.document_id.in_(visible_document_ids),
            ReferralPipelineEvent.case_id.in_(visible_case_ids),
        )
    )
    rows = (
        query.order_by(ReferralPipelineEvent.created_at.desc(), ReferralPipelineEvent.id.desc())
        .limit(bounded_limit)
        .all()
    )
    return [event_to_read(event) for event in rows]
