from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db.models import Document, ReferralCase
from backend.app.documents.registry import parse_document, register_file
from backend.app.referral.completeness import check_completeness
from backend.app.referral.evidence import align_to_pages
from backend.app.referral.ocr_quality import evaluate_ocr_quality
from backend.app.referral.pipeline_events import record_pipeline_event
from backend.app.referral.prompts import REFERRAL_PROMPT_VERSION
from backend.app.referral.routing import enforce_allowed_routing
from backend.app.referral.schemas import ReferralAnalysis
from backend.app.referral.service import should_require_review
from backend.app.referral.statuses import (
    PIPELINE_STAGE_INBOX,
    PIPELINE_STAGE_MODEL,
    PIPELINE_STAGE_OCR,
    PIPELINE_STAGE_PYPDF,
    PIPELINE_STAGE_VALIDATION,
    PIPELINE_STAGE_WORKLIST,
    PIPELINE_STATUS_COMPLETED,
    PIPELINE_STATUS_OK,
    PIPELINE_STATUS_STARTED,
    PIPELINE_STATUS_WARNING,
    STATUS_ANALYSIS_READY,
)
from backend.app.referral.text_extraction import apply_text_extraction_fallback
from backend.app.security.groups import GROUP_REFERRAL_REVIEWERS

DEMO_PRELOAD_MODEL_PROFILE = "demo-preloaded-sample"
DEMO_PRELOAD_SOURCE_SYSTEM = "demo_referral_filesystem"


def _sample_pdfs(source_dir: Path) -> list[Path]:
    if not source_dir.exists():
        return []
    return sorted(
        path
        for path in source_dir.iterdir()
        if path.suffix.lower() == ".pdf" and not path.stem.endswith(" 2")
    )


def _already_has_referral_demo_state(session: Session) -> bool:
    if session.query(ReferralCase.id).first() is not None:
        return True
    return (
        session.query(Document.id)
        .filter(Document.source_system == DEMO_PRELOAD_SOURCE_SYSTEM)
        .first()
        is not None
    )


def _ocr_message_and_status(ocr_quality) -> tuple[str, str]:
    if ocr_quality.status == "failed":
        return f"OCR confidence {ocr_quality.min_confidence or 0:.2f}, human review required", "failed"
    if ocr_quality.status == "low":
        return f"OCR low confidence {ocr_quality.min_confidence or 0:.2f}, human review required", "warning"
    if ocr_quality.status == "ok":
        return f"OCR confidence {ocr_quality.min_confidence:.2f}", "ok"
    return "OCR fallback not required", "ok"


def _copy_to_inbox(sample: Path, inbox_dir: Path) -> Path:
    inbox_dir.mkdir(parents=True, exist_ok=True)
    target = inbox_dir / sample.name
    if not target.exists():
        shutil.copyfile(sample, target)
    return target


def _preload_one(session: Session, sample: Path) -> None:
    settings = get_settings()
    inbox_path = _copy_to_inbox(sample, settings.referral_inbox_dir)
    document = register_file(
        session,
        inbox_path,
        source_system=DEMO_PRELOAD_SOURCE_SYSTEM,
        access_groups=[GROUP_REFERRAL_REVIEWERS],
        contains_patient_data=True,
        copy_to_uploads=False,
    )
    record_pipeline_event(
        session,
        stage=PIPELINE_STAGE_INBOX,
        status=PIPELINE_STATUS_OK,
        message=f"PDF-Inbox: preloaded {document.title}",
        document_id=document.id,
        payload={"source_system": document.source_system, "decision": "preloaded"},
        commit=True,
    )
    record_pipeline_event(
        session,
        stage=PIPELINE_STAGE_PYPDF,
        status=PIPELINE_STATUS_STARTED,
        message="PyPDF/Text extraction started",
        document_id=document.id,
        commit=True,
    )
    parsed = parse_document(session, document)
    record_pipeline_event(
        session,
        stage=PIPELINE_STAGE_PYPDF,
        status=PIPELINE_STATUS_OK,
        message=f"PyPDF extracted {len(parsed.text)} characters across {len(parsed.pages)} pages",
        document_id=document.id,
        payload={"character_count": len(parsed.text), "page_count": len(parsed.pages)},
        commit=True,
    )
    ocr_quality = evaluate_ocr_quality(parsed.pages, settings.ocr_min_confidence)
    ocr_message, ocr_status = _ocr_message_and_status(ocr_quality)
    record_pipeline_event(
        session,
        stage=PIPELINE_STAGE_OCR,
        status=ocr_status,
        message=ocr_message,
        document_id=document.id,
        payload={"ocr_min_confidence": ocr_quality.min_confidence, "ocr_status": ocr_quality.status},
        commit=True,
    )

    analysis = ReferralAnalysis(document_id=document.id, document_type="referral")
    analysis = apply_text_extraction_fallback(analysis, parsed.text)
    analysis = enforce_allowed_routing(analysis)
    analysis.missing_items = check_completeness(analysis)
    analysis.evidence = align_to_pages(analysis.evidence, parsed)
    analysis.ocr_min_confidence = ocr_quality.min_confidence
    analysis.ocr_status = ocr_quality.status
    if ocr_quality.human_review_required:
        analysis.human_review_required = True
    for warning in ocr_quality.warnings:
        if warning not in analysis.warnings:
            analysis.warnings.append(warning)
    analysis.human_review_required = should_require_review(analysis)

    routing_target = analysis.routing_proposal.routing_target or "unclear"
    confidence = analysis.routing_proposal.confidence
    record_pipeline_event(
        session,
        stage=PIPELINE_STAGE_MODEL,
        status=PIPELINE_STATUS_OK,
        message=f"Preloaded demo analysis: {routing_target}, confidence {confidence:.2f}",
        document_id=document.id,
        payload={
            "model_profile": DEMO_PRELOAD_MODEL_PROFILE,
            "routing_target": analysis.routing_proposal.routing_target,
            "confidence": confidence,
            "preloaded": True,
        },
    )
    validation_status = (
        PIPELINE_STATUS_WARNING
        if analysis.missing_items or analysis.human_review_required
        else PIPELINE_STATUS_OK
    )
    record_pipeline_event(
        session,
        stage=PIPELINE_STAGE_VALIDATION,
        status=validation_status,
        message=f"Validation complete: {len(analysis.missing_items)} missing items",
        document_id=document.id,
        payload={
            "missing_count": len(analysis.missing_items),
            "human_review_required": analysis.human_review_required,
        },
    )
    case = ReferralCase(
        id=uuid.uuid4().hex,
        document_id=document.id,
        status=STATUS_ANALYSIS_READY,
        analysis_json=analysis.model_dump(mode="json"),
        model_profile=DEMO_PRELOAD_MODEL_PROFILE,
        prompt_version=REFERRAL_PROMPT_VERSION,
        created_by="demo_preload",
    )
    session.add(case)
    session.flush()
    record_pipeline_event(
        session,
        stage=PIPELINE_STAGE_WORKLIST,
        status=PIPELINE_STATUS_COMPLETED,
        message="Available in review worklist",
        document_id=document.id,
        case_id=case.id,
    )
    session.commit()


def preload_referral_demo_state(session: Session) -> int:
    settings = get_settings()
    if not settings.demo_preload_referrals_enabled:
        return 0
    if settings.referral_inbox_backend != "filesystem":
        return 0
    if _already_has_referral_demo_state(session):
        return 0

    count = 0
    for sample in _sample_pdfs(settings.demo_preload_referrals_dir):
        _preload_one(session, sample)
        count += 1
    return count
