from __future__ import annotations

from collections import Counter
from statistics import fmean

from sqlalchemy.orm import Session

from backend.app.core.time import utc_now
from backend.app.db.models import ReferralCase
from backend.app.referral.schemas import MissingFieldCount, ReferralAnalysis, ReferralBatchSummary, ReferralWorklistItem
from backend.app.referral.statuses import (
    STATUS_ANALYSIS_READY,
    STATUS_REVIEW_CONFIRM,
    STATUS_REVIEW_CORRECT,
    STATUS_REVIEW_PREFIX,
    STATUS_WRITEBACK_SENT,
    WORKLIST_ACTIVE_EXCLUDED_STATUSES,
)
from backend.app.referral.worklist import is_route_unclear, list_referral_worklist, model_error_countable
from backend.app.security.auth import DemoUser


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(fmean(values), 4)


def _missing_field_counts(session: Session, items: list[ReferralWorklistItem]) -> list[MissingFieldCount]:
    case_ids = [item.case_id for item in items if item.case_id]
    if not case_ids:
        return []
    cases = session.query(ReferralCase).filter(ReferralCase.id.in_(case_ids)).all()
    counter: Counter[str] = Counter()
    for case in cases:
        analysis = ReferralAnalysis.model_validate(case.analysis_json)
        counter.update(item.field for item in analysis.missing_items)
    return [MissingFieldCount(field=field, count=count) for field, count in counter.most_common(8)]


def compute_referral_batch_summary(session: Session, user: DemoUser) -> ReferralBatchSummary:
    items = list_referral_worklist(session, user, "all")
    analyzed_items = [item for item in items if item.case_id is not None]
    ready_to_forward = sum(1 for item in items if item.status in {STATUS_REVIEW_CONFIRM, STATUS_REVIEW_CORRECT})
    routing_distribution: Counter[str] = Counter()
    for item in analyzed_items:
        routing_distribution.update([item.routing_target or "unclear"])

    confidence_values = [item.confidence for item in analyzed_items if item.confidence is not None]
    ocr_values = [item.ocr_min_confidence for item in analyzed_items if item.ocr_min_confidence is not None]

    return ReferralBatchSummary(
        total_documents=len(items),
        active_worklist=sum(1 for item in items if item.status not in WORKLIST_ACTIVE_EXCLUDED_STATUSES),
        open_items=sum(1 for item in items if item.status in {"new", STATUS_ANALYSIS_READY}),
        new_documents=sum(1 for item in items if item.case_id is None),
        analyzed=len(analyzed_items),
        review_required=sum(1 for item in items if item.human_review_required),
        ready_to_forward=ready_to_forward,
        forwarded=sum(1 for item in items if item.status == STATUS_WRITEBACK_SENT),
        ocr_low=sum(1 for item in items if item.ocr_status == "low"),
        ocr_failed=sum(1 for item in items if item.ocr_status == "failed"),
        route_unclear=sum(1 for item in items if is_route_unclear(item)),
        model_errors=sum(1 for item in items if model_error_countable(item)),
        confirmed=sum(1 for item in items if item.status == STATUS_REVIEW_CONFIRM),
        corrected=sum(1 for item in items if item.status == STATUS_REVIEW_CORRECT),
        rejected=sum(1 for item in items if item.status == f"{STATUS_REVIEW_PREFIX}reject"),
        questions=sum(1 for item in items if item.status == f"{STATUS_REVIEW_PREFIX}question"),
        routing_distribution=dict(routing_distribution),
        top_missing_fields=_missing_field_counts(session, items),
        average_confidence=_average(confidence_values),
        average_ocr_confidence=_average(ocr_values),
        generated_at=utc_now(),
    )
