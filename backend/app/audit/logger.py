from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.audit.events import AuditPayload, new_id
from backend.app.core.config import get_settings
from backend.app.db.models import AuditEvent
from backend.app.security.auth import DemoUser


def log_event(session: Session, actor: DemoUser, payload: AuditPayload, *, commit: bool = True) -> None:
    settings = get_settings()
    if not settings.audit_log_enabled:
        return
    event = AuditEvent(
        id=new_id(),
        actor_id=actor.id,
        actor_role=actor.role,
        action=payload.action,
        object_type=payload.object_type,
        object_id=payload.object_id,
        payload_json=payload.payload_json,
        model_profile=payload.model_profile,
        prompt_version=payload.prompt_version,
        input_hash=payload.input_hash,
        output_hash=payload.output_hash,
        decision_before=payload.decision_before if settings.store_model_output_text else None,
        decision_after=payload.decision_after if settings.store_model_output_text else None,
    )
    session.add(event)
    if commit:
        session.commit()
