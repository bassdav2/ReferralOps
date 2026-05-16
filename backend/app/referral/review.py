from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from backend.app.audit.events import AuditPayload
from backend.app.audit.logger import log_event
from backend.app.core.config import get_settings
from backend.app.core.errors import bad_request
from backend.app.core.time import utc_now
from backend.app.db.models import ReferralReview
from backend.app.referral.demo_outputs import write_review_demo_output
from backend.app.referral.pipeline_events import record_pipeline_event
from backend.app.referral.routing import enforce_allowed_routing
from backend.app.referral.schemas import ReviewRead, ReviewRequest
from backend.app.referral.statuses import (
    PIPELINE_STAGE_OUTPUT,
    PIPELINE_STAGE_REVIEW,
    PIPELINE_STATUS_COMPLETED,
    PIPELINE_STATUS_FAILED,
    REVIEW_DECISION_LABELS,
    STATUS_REVIEW_PREFIX,
    STATUS_WRITEBACK_SENT,
)
from backend.app.security.acl import require_referral_case_visible, require_referral_reviewer
from backend.app.security.auth import DemoUser


def review_referral_case(
    session: Session, case_id: str, user: DemoUser, request: ReviewRequest
) -> ReviewRead:
    require_referral_reviewer(user)
    case = require_referral_case_visible(session, case_id, user)
    if case.status == STATUS_WRITEBACK_SENT:
        raise bad_request("Review cannot be changed after writeback has been sent.")

    before = case.analysis_json
    corrected_analysis = (
        enforce_allowed_routing(request.corrected_analysis) if request.corrected_analysis else None
    )
    if corrected_analysis and corrected_analysis.document_id != case.document_id:
        raise bad_request("Corrected analysis document_id must match the referral case document.")
    corrected = corrected_analysis.model_dump(mode="json") if corrected_analysis else None
    review = ReferralReview(
        id=uuid.uuid4().hex,
        case_id=case_id,
        reviewer_id=user.id,
        decision=request.decision,
        corrected_json=corrected,
        comment=request.comment,
    )
    case.status = f"{STATUS_REVIEW_PREFIX}{request.decision}"
    case.reviewed_at = utc_now()
    if corrected is not None:
        case.analysis_json = corrected
    session.add(review)
    session.flush()
    record_pipeline_event(
        session,
        stage=PIPELINE_STAGE_REVIEW,
        status=PIPELINE_STATUS_COMPLETED,
        message=REVIEW_DECISION_LABELS.get(request.decision, request.decision),
        document_id=case.document_id,
        case_id=case.id,
        payload={"decision": request.decision, "reviewer": user.id},
    )
    output_warning = None
    if get_settings().demo_outputs_enabled:
        output_result = write_review_demo_output(
            session,
            case=case,
            review=review,
            user=user,
            comment=request.comment,
        )
        if output_result.written:
            record_pipeline_event(
                session,
                stage=PIPELINE_STAGE_OUTPUT,
                status=PIPELINE_STATUS_COMPLETED,
                message=f"Demo output written: {output_result.relative_path}",
                document_id=case.document_id,
                case_id=case.id,
                payload={"path": output_result.relative_path, "decision": request.decision},
            )
        else:
            output_warning = output_result.warning
            record_pipeline_event(
                session,
                stage=PIPELINE_STAGE_OUTPUT,
                status=PIPELINE_STATUS_FAILED,
                message=output_warning or "Demo output failed",
                document_id=case.document_id,
                case_id=case.id,
                payload={"decision": request.decision},
            )
    log_event(
        session,
        user,
        AuditPayload(
            action="referral.review",
            object_type="referral_case",
            object_id=case_id,
            payload_json={"decision": request.decision, "comment": request.comment},
            decision_before=before,
            decision_after=corrected or before,
        ),
        commit=False,
    )
    session.commit()
    session.refresh(review)
    return ReviewRead(
        id=review.id,
        case_id=review.case_id,
        reviewer_id=review.reviewer_id,
        decision=review.decision,
        created_at=review.created_at,
        warning=output_warning,
    )
