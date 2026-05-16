from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.time import utc_now
from backend.app.db.models import Document, ReferralCase, ReferralReview
from backend.app.referral.schemas import ReferralAnalysis, ReferralDemoOutputRead
from backend.app.referral.statuses import REVIEW_DECISION_LABELS, REVIEW_DECISION_OUTPUT_FOLDERS
from backend.app.security.acl import has_group_overlap, is_admin, require_referral_reviewer
from backend.app.security.auth import DemoUser

DEMO_OUTPUT_FOLDERS = [*REVIEW_DECISION_OUTPUT_FOLDERS.values(), "writeback", "departments"]

MISSING_FIELD_LABELS = {
    "patient.name": "Patientenname",
    "patient.birth_date": "Geburtsdatum",
    "patient.phone": "Telefon Patient",
    "patient.insurance_id": "Versicherungsnummer",
    "referring_party.physician_name": "Zuweisender Arzt",
    "referring_party.organization": "Zuweisende Organisation",
    "clinical_context_for_admin_routing.reason_for_referral": "Grund der Zuweisung",
    "attachments.lab": "Laborbeilage",
    "attachments.imaging": "Bildgebung",
    "attachments.medication_list": "Medikamentenliste",
    "attachments.prior_reports": "Vorberichte",
    "attachments.consent_form": "Einwilligung",
}


@dataclass(frozen=True)
class DemoOutputWriteResult:
    written: bool
    relative_path: str | None = None
    file_name: str | None = None
    warning: str | None = None
    extra_paths: tuple[str, ...] = ()


def output_folder_for_decision(decision: str) -> str:
    try:
        return REVIEW_DECISION_OUTPUT_FOLDERS[decision]
    except KeyError as exc:
        raise ValueError(f"Unsupported review decision: {decision}") from exc


def output_folder_for_department(routing_target: str | None) -> str:
    return f"departments/{_safe_filename_part(routing_target or 'unklare_route', default='unklare_route')}"


def _safe_filename_part(value: str, *, default: str = "referral") -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return safe[:90] or default


def _safe_timestamp(timestamp: datetime) -> str:
    normalized = timestamp.astimezone().isoformat(timespec="seconds")
    return re.sub(r"[^0-9A-Za-z]+", "", normalized)


def _source_pointer(document: Document | None) -> str | None:
    if document is None:
        return None
    raw = document.source_uri or document.storage_pointer or document.external_id
    if raw is None:
        return None
    if raw.startswith(("minio://", "s3://", "file://")):
        return raw
    path = Path(raw)
    if path.is_absolute():
        try:
            return path.relative_to(get_settings().project_root).as_posix()
        except ValueError:
            return path.name
    return raw


def ensure_demo_output_folders(base_dir: Path | None = None) -> Path:
    root = base_dir or get_settings().referral_demo_output_dir
    for folder in DEMO_OUTPUT_FOLDERS:
        (root / folder).mkdir(parents=True, exist_ok=True)
    try:
        from backend.app.referral.routing import allowed_targets

        for routing_target in allowed_targets():
            (root / output_folder_for_department(routing_target)).mkdir(parents=True, exist_ok=True)
    except (OSError, KeyError, TypeError, ValueError):
        # Output writing must not fail just because optional routing config is unavailable.
        pass
    return root


def _output_payload(
    *,
    case: ReferralCase,
    review: ReferralReview,
    document: Document | None,
    user: DemoUser,
    comment: str | None,
) -> dict:
    analysis = ReferralAnalysis.model_validate(case.analysis_json)
    timestamp = review.created_at or utc_now()
    routing = analysis.routing_proposal
    missing_fields = [item.field for item in analysis.missing_items]
    return {
        "case_id": case.id,
        "document_id": case.document_id,
        "document_title": document.title if document else None,
        "decision": review.decision,
        "decision_label": REVIEW_DECISION_LABELS.get(review.decision, review.decision),
        "routing_target": routing.routing_target,
        "department": routing.department,
        "referring_physician": analysis.referring_party.physician_name,
        "referring_organization": analysis.referring_party.organization,
        "referring_email": analysis.referring_party.email,
        "model_confidence": routing.confidence,
        "missing_fields": missing_fields,
        "missing_field_labels": [MISSING_FIELD_LABELS.get(field, field) for field in missing_fields],
        "human_review_required": analysis.human_review_required,
        "reviewer": user.id,
        "timestamp": timestamp.isoformat(),
        "source_pdf": _source_pointer(document),
        "model_profile": case.model_profile,
        "prompt_version": case.prompt_version,
        "comment": comment,
    }


def write_review_demo_output(
    session: Session,
    *,
    case: ReferralCase,
    review: ReferralReview,
    user: DemoUser,
    comment: str | None,
) -> DemoOutputWriteResult:
    try:
        base_dir = ensure_demo_output_folders()
        folder = output_folder_for_decision(review.decision)
        document = session.get(Document, case.document_id)
        timestamp = review.created_at or utc_now()
        title = _safe_filename_part(document.title if document else case.document_id)
        filename = f"{_safe_timestamp(timestamp)}_{title}_{case.id[:12]}_{review.decision}.json"
        relative_path = f"{folder}/{filename}"
        payload = _output_payload(case=case, review=review, document=document, user=user, comment=comment)
        (base_dir / relative_path).write_text(
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return DemoOutputWriteResult(written=True, relative_path=relative_path, file_name=filename)
    except Exception as exc:
        return DemoOutputWriteResult(written=False, warning=f"Demo output could not be written: {exc}")


def write_writeback_demo_output(
    session: Session,
    *,
    case: ReferralCase,
    user: DemoUser,
) -> DemoOutputWriteResult:
    try:
        base_dir = ensure_demo_output_folders()
        review = (
            session.query(ReferralReview)
            .filter(ReferralReview.case_id == case.id)
            .order_by(ReferralReview.created_at.desc(), ReferralReview.id.desc())
            .first()
        )
        if review is None:
            return DemoOutputWriteResult(written=False, warning="Demo writeback requires a review decision first.")
        document = session.get(Document, case.document_id)
        timestamp = utc_now()
        title = _safe_filename_part(document.title if document else case.document_id)
        filename = f"{_safe_timestamp(timestamp)}_{title}_{case.id[:12]}_writeback.json"
        relative_path = f"writeback/{filename}"
        payload = _output_payload(case=case, review=review, document=document, user=user, comment=review.comment)
        payload["decision"] = "writeback"
        payload["decision_label"] = "Weitergeleitet"
        payload["review_decision"] = review.decision
        payload["writeback_mode"] = "local_demo_json"
        payload["timestamp"] = timestamp.isoformat()
        department_relative_path = f"{output_folder_for_department(payload.get('routing_target'))}/{filename}"
        payload["department_output_path"] = department_relative_path
        (base_dir / relative_path).write_text(
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (base_dir / department_relative_path).parent.mkdir(parents=True, exist_ok=True)
        (base_dir / department_relative_path).write_text(
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return DemoOutputWriteResult(
            written=True,
            relative_path=relative_path,
            file_name=filename,
            extra_paths=(department_relative_path,),
        )
    except Exception as exc:
        return DemoOutputWriteResult(written=False, warning=f"Demo writeback output could not be written: {exc}")


def _read_output(path: Path, base_dir: Path) -> ReferralDemoOutputRead | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    created_at = None
    if payload.get("timestamp"):
        try:
            created_at = datetime.fromisoformat(payload["timestamp"])
        except ValueError:
            created_at = None
    if created_at is None:
        try:
            created_at = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        except OSError:
            created_at = None
    return ReferralDemoOutputRead(
        decision=str(payload.get("decision") or path.parent.name),
        decision_label=payload.get("decision_label"),
        file_name=path.name,
        relative_path=path.relative_to(base_dir).as_posix(),
        case_id=payload.get("case_id"),
        document_id=payload.get("document_id"),
        document_title=payload.get("document_title"),
        department=payload.get("department"),
        routing_target=payload.get("routing_target"),
        referring_organization=payload.get("referring_organization"),
        referring_physician=payload.get("referring_physician"),
        created_at=created_at,
    )


def list_demo_outputs(session: Session, user: DemoUser, *, limit: int = 50) -> list[ReferralDemoOutputRead]:
    require_referral_reviewer(user)
    base_dir = ensure_demo_output_folders()
    bounded_limit = max(1, min(limit, 200))
    if is_admin(user):
        visible_documents = {document.id for document in session.query(Document).all() if document.access_groups}
    else:
        visible_documents = {
            document.id
            for document in session.query(Document).all()
            if has_group_overlap(user, document.access_groups)
        }
    outputs: list[ReferralDemoOutputRead] = []
    for path in base_dir.rglob("*.json"):
        item = _read_output(path, base_dir)
        if item is None:
            continue
        if item.document_id and item.document_id not in visible_documents:
            continue
        outputs.append(item)
    outputs.sort(key=lambda item: item.created_at.timestamp() if item.created_at else 0.0, reverse=True)
    return outputs[:bounded_limit]
