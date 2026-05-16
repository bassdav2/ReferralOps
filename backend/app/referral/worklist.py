from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session

from backend.app.db.models import Document, ReferralCase, ReferralPipelineEvent
from backend.app.referral.schemas import (
    ReferralAnalysis,
    ReferralPipelineStageStatus,
    ReferralWorklistFilter,
    ReferralWorklistItem,
    ReferralWorklistPipelineStatus,
)
from backend.app.referral.statuses import STATUS_REVIEW_CONFIRM, STATUS_REVIEW_PREFIX, WORKLIST_ACTIVE_EXCLUDED_STATUSES
from backend.app.security.acl import has_group_overlap, is_admin, require_referral_reviewer
from backend.app.security.auth import DemoUser

FILTER_ALL = "all"
FILTER_ACTIVE = "active"
FILTER_NEW = "new"
FILTER_REVIEW_REQUIRED = "review_required"
FILTER_OCR_LOW = "ocr_low"
FILTER_ROUTE_UNCLEAR = "route_unclear"
FILTER_CONFIRMED = "confirmed"
FILTER_REJECTED = "rejected"


def _can_see_document(user: DemoUser, document: Document) -> bool:
    return bool(document.access_groups) and (is_admin(user) or has_group_overlap(user, document.access_groups))


def _model_error_exists(warnings: Iterable[str]) -> bool:
    markers = ("model", "gateway", "invalid json", "did not validate", "returned invalid")
    return any(any(marker in warning.lower() for marker in markers) for warning in warnings)


def is_route_unclear(item: ReferralWorklistItem) -> bool:
    return (
        item.routing_target is None
        or item.confidence is None
        or item.confidence < 0.6
        or _model_error_exists(item.warnings)
    )


def model_error_countable(item: ReferralWorklistItem) -> bool:
    return _model_error_exists(item.warnings)


def visible_referral_documents(session: Session, user: DemoUser) -> list[Document]:
    require_referral_reviewer(user)
    rows = session.query(Document).order_by(Document.ingested_at.desc()).all()
    return [row for row in rows if _can_see_document(user, row)]


def latest_cases_by_document(session: Session, document_ids: list[str]) -> dict[str, ReferralCase]:
    if not document_ids:
        return {}
    cases = (
        session.query(ReferralCase)
        .filter(ReferralCase.document_id.in_(document_ids))
        .order_by(ReferralCase.document_id.asc(), ReferralCase.created_at.desc(), ReferralCase.id.desc())
        .all()
    )
    latest: dict[str, ReferralCase] = {}
    for case in cases:
        latest.setdefault(case.document_id, case)
    return latest


def _stage(status: str, label: str, detail: str | None = None) -> ReferralPipelineStageStatus:
    return ReferralPipelineStageStatus(status=status, label=label, detail=detail)


def _ocr_pipeline_status(analysis: ReferralAnalysis | None) -> ReferralPipelineStageStatus:
    if analysis is None:
        return _stage("pending", "OCR", "ausstehend")
    if analysis.ocr_status == "ok":
        return _stage("ok", _ocr_label(analysis.ocr_min_confidence), "OCR ok")
    if analysis.ocr_status == "low":
        return _stage("warning", _ocr_label(analysis.ocr_min_confidence), "OCR schwach")
    if analysis.ocr_status == "failed":
        return _stage("failed", "OCR", "OCR fehlgeschlagen")
    return _stage("unknown", "OCR", "kein OCR-Fallback")


def _ocr_label(confidence: float | None) -> str:
    if confidence is None:
        return "OCR"
    return f"OCR {round(confidence * 100)}%"


def _model_pipeline_status(analysis: ReferralAnalysis | None) -> ReferralPipelineStageStatus:
    if analysis is None:
        return _stage("pending", "Gemma", "ausstehend")
    if _model_error_exists(analysis.warnings):
        return _stage("failed", "Gemma", "Modell-Fallback")
    if analysis.routing_proposal.confidence < 0.6 or analysis.routing_proposal.routing_target is None:
        return _stage("warning", "Gemma", "Route unklar")
    return _stage("ok", "Gemma", f"{analysis.routing_proposal.confidence:.2f}")


def _review_pipeline_status(case: ReferralCase | None) -> ReferralPipelineStageStatus:
    if case is None:
        return _stage("pending", "Review", "ausstehend")
    if case.reviewed_at is not None or case.status.startswith(STATUS_REVIEW_PREFIX):
        return _stage("completed", "Review", "abgeschlossen")
    return _stage("pending", "Review", "offen")


def _output_pipeline_status(output_completed: bool) -> ReferralPipelineStageStatus:
    if output_completed:
        return _stage("completed", "Output", "JSON geschrieben")
    return _stage("pending", "Output", "-")


def _pipeline_status(
    document: Document,
    case: ReferralCase | None,
    analysis: ReferralAnalysis | None,
    output_completed: bool,
) -> ReferralWorklistPipelineStatus:
    pypdf_status = "ok" if document.parse_status == "parsed" or case is not None else "pending"
    return ReferralWorklistPipelineStatus(
        inbox=_stage("ok", "Inbox", document.source_system),
        pypdf=_stage(pypdf_status, "PyPDF", "Text extrahiert" if pypdf_status == "ok" else "ausstehend"),
        ocr=_ocr_pipeline_status(analysis),
        model=_model_pipeline_status(analysis),
        review=_review_pipeline_status(case),
        output=_output_pipeline_status(output_completed),
    )


def _output_completed_case_ids(session: Session, case_ids: list[str]) -> set[str]:
    if not case_ids:
        return set()
    rows = (
        session.query(ReferralPipelineEvent.case_id)
        .filter(
            ReferralPipelineEvent.case_id.in_(case_ids),
            ReferralPipelineEvent.stage == "output",
            ReferralPipelineEvent.status == "completed",
        )
        .all()
    )
    return {case_id for (case_id,) in rows if case_id}


def case_to_worklist_item(
    document: Document,
    case: ReferralCase | None,
    *,
    output_completed: bool = False,
) -> ReferralWorklistItem:
    if case is None:
        return ReferralWorklistItem(
            case_id=None,
            document_id=document.id,
            document_title=document.title,
            source_system=document.source_system,
            status="new",
            routing_target=None,
            department=None,
            confidence=None,
            human_review_required=False,
            missing_count=0,
            ocr_min_confidence=None,
            ocr_status="unknown",
            warnings=[],
            created_at=document.ingested_at,
            reviewed_at=None,
            pipeline=_pipeline_status(document, None, None, False),
        )

    analysis = ReferralAnalysis.model_validate(case.analysis_json)
    routing = analysis.routing_proposal
    return ReferralWorklistItem(
        case_id=case.id,
        document_id=document.id,
        document_title=document.title,
        source_system=document.source_system,
        status=case.status,
        routing_target=routing.routing_target,
        department=routing.department,
        confidence=routing.confidence,
        human_review_required=analysis.human_review_required,
        missing_count=len(analysis.missing_items),
        ocr_min_confidence=analysis.ocr_min_confidence,
        ocr_status=analysis.ocr_status,
        warnings=analysis.warnings,
        created_at=case.created_at,
        reviewed_at=case.reviewed_at,
        pipeline=_pipeline_status(document, case, analysis, output_completed),
    )


def _matches_filter(item: ReferralWorklistItem, filter_value: ReferralWorklistFilter) -> bool:
    if filter_value == FILTER_ACTIVE:
        return item.status not in WORKLIST_ACTIVE_EXCLUDED_STATUSES
    if filter_value == FILTER_ALL:
        return True
    if filter_value == FILTER_NEW:
        return item.case_id is None
    if filter_value == FILTER_REVIEW_REQUIRED:
        return item.human_review_required
    if filter_value == FILTER_OCR_LOW:
        return item.ocr_status in {"low", "failed"}
    if filter_value == FILTER_ROUTE_UNCLEAR:
        return is_route_unclear(item)
    if filter_value == FILTER_CONFIRMED:
        return item.status == STATUS_REVIEW_CONFIRM
    if filter_value == FILTER_REJECTED:
        return item.status == f"{STATUS_REVIEW_PREFIX}reject"
    return True


def list_referral_worklist(
    session: Session,
    user: DemoUser,
    filter_value: ReferralWorklistFilter = FILTER_ALL,
) -> list[ReferralWorklistItem]:
    documents = visible_referral_documents(session, user)
    latest = latest_cases_by_document(session, [document.id for document in documents])
    output_completed = _output_completed_case_ids(session, [case.id for case in latest.values()])
    items = [
        case_to_worklist_item(
            document,
            latest.get(document.id),
            output_completed=latest.get(document.id).id in output_completed if latest.get(document.id) else False,
        )
        for document in documents
    ]
    return [item for item in items if _matches_filter(item, filter_value)]
