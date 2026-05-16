from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.db.models import AuditEvent


def export_audit_jsonl(session: Session, target: Path) -> int:
    count = 0
    with target.open("w", encoding="utf-8") as handle:
        for event in session.query(AuditEvent).order_by(AuditEvent.created_at.asc()).all():
            handle.write(
                json.dumps(
                    {
                        "id": event.id,
                        "actor_id": event.actor_id,
                        "action": event.action,
                        "object_type": event.object_type,
                        "object_id": event.object_id,
                        "created_at": event.created_at.isoformat(),
                        "payload_json": event.payload_json,
                    },
                    ensure_ascii=True,
                    default=str,
                )
                + "\n"
            )
            count += 1
    return count

