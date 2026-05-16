from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.db.models import AuditEvent
from backend.app.db.session import get_session
from backend.app.security.acl import require_admin
from backend.app.security.auth import DemoUser, get_current_user

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/audit")
def audit_events(
    session: Session = Depends(get_session),
    user: DemoUser = Depends(get_current_user),
) -> list[dict]:
    require_admin(user)
    events = session.query(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(100).all()
    return [
        {
            "id": event.id,
            "actor_id": event.actor_id,
            "action": event.action,
            "object_type": event.object_type,
            "object_id": event.object_id,
            "created_at": event.created_at.isoformat(),
            "payload_json": event.payload_json,
        }
        for event in events
    ]
