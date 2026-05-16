from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.audit.events import AuditPayload
from backend.app.audit.logger import log_event
from backend.app.core.config import get_settings
from backend.app.core.errors import bad_request
from backend.app.db.models import ReferralPipelineEvent
from backend.app.referral.demo_outputs import write_writeback_demo_output
from backend.app.referral.pipeline_events import record_pipeline_event
from backend.app.referral.statuses import (
    PIPELINE_STAGE_OUTPUT,
    PIPELINE_STAGE_WRITEBACK,
    PIPELINE_STATUS_COMPLETED,
    PIPELINE_STATUS_FAILED,
    PIPELINE_STATUS_OK,
    STATUS_WRITEBACK_SENT,
    WRITEBACK_ALLOWED_STATUSES,
)
from backend.app.security.acl import require_referral_case_visible, require_referral_reviewer
from backend.app.security.auth import DemoUser


def _existing_writeback_result(session: Session, case_id: str, *, writeback_enabled: bool) -> dict:
    event = (
        session.query(ReferralPipelineEvent)
        .filter(
            ReferralPipelineEvent.case_id == case_id,
            ReferralPipelineEvent.stage == PIPELINE_STAGE_WRITEBACK,
            ReferralPipelineEvent.status == PIPELINE_STATUS_OK,
        )
        .order_by(ReferralPipelineEvent.created_at.desc(), ReferralPipelineEvent.id.desc())
        .first()
    )
    payload = event.payload_json if event and event.payload_json else {}
    return {
        "status": "local_json_written" if writeback_enabled else "demo_written",
        "message": "Writeback already sent; returning existing output.",
        "case_id": case_id,
        "path": payload.get("path"),
        "extra_paths": list(payload.get("extra_paths") or []),
    }


def writeback_case(session: Session, case_id: str, user: DemoUser) -> dict:
    require_referral_reviewer(user)
    case = require_referral_case_visible(session, case_id, user)
    settings = get_settings()
    log_event(
        session,
        user,
        AuditPayload(
            action="referral.writeback.attempt",
            object_type="referral_case",
            object_id=case_id,
            payload_json={"status": case.status},
        ),
    )
    if case.status == STATUS_WRITEBACK_SENT:
        return _existing_writeback_result(session, case_id, writeback_enabled=settings.writeback_enabled)
    if case.status not in WRITEBACK_ALLOWED_STATUSES:
        raise bad_request("Writeback requires a confirmed or corrected human review decision.")
    output_result = write_writeback_demo_output(session, case=case, user=user)
    if output_result.written:
        record_pipeline_event(
            session,
            stage=PIPELINE_STAGE_OUTPUT,
            status=PIPELINE_STATUS_COMPLETED,
            message=f"Demo writeback output written: {output_result.relative_path}",
            document_id=case.document_id,
            case_id=case_id,
            payload={"path": output_result.relative_path, "extra_paths": list(output_result.extra_paths)},
        )
    else:
        record_pipeline_event(
            session,
            stage=PIPELINE_STAGE_OUTPUT,
            status=PIPELINE_STATUS_FAILED,
            message=output_result.warning or "Demo writeback output failed",
            document_id=case.document_id,
            case_id=case_id,
        )
        session.commit()
        return {"status": "warning", "message": output_result.warning or "Demo writeback output failed"}

    case.status = STATUS_WRITEBACK_SENT
    session.flush()
    if not settings.writeback_enabled:
        record_pipeline_event(
            session,
            stage=PIPELINE_STAGE_WRITEBACK,
            status=PIPELINE_STATUS_OK,
            message="Demo writeback completed: local JSON only",
            document_id=case.document_id,
            case_id=case_id,
            payload={
                "status": case.status,
                "path": output_result.relative_path,
                "extra_paths": list(output_result.extra_paths),
            },
        )
        log_event(
            session,
            user,
            AuditPayload(
                action="referral.writeback.disabled",
                object_type="referral_case",
                object_id=case_id,
                payload_json={"status": case.status},
            ),
        )
        return {
            "status": "demo_written",
            "message": "Demo writeback completed as local JSON. No real KIS/DMS writeback.",
            "path": output_result.relative_path,
            "extra_paths": list(output_result.extra_paths),
        }
    record_pipeline_event(
        session,
        stage=PIPELINE_STAGE_WRITEBACK,
        status=PIPELINE_STATUS_OK,
        message="Local JSON writeback completed",
        document_id=case.document_id,
        case_id=case_id,
        payload={
            "status": case.status,
            "path": output_result.relative_path,
            "extra_paths": list(output_result.extra_paths),
        },
    )
    log_event(
        session,
        user,
        AuditPayload(
            action="referral.writeback.local_json_written",
            object_type="referral_case",
            object_id=case_id,
            payload_json={"status": case.status},
        ),
    )
    return {
        "status": "local_json_written",
        "case_id": case_id,
        "path": output_result.relative_path,
        "extra_paths": list(output_result.extra_paths),
    }
