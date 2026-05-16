from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from backend.app.audit.events import AuditPayload, hash_json
from backend.app.audit.logger import log_event
from backend.app.core.config import get_settings
from backend.app.core.runtime_model_config import effective_model_config
from backend.app.db.models import ReferralCase
from backend.app.documents.registry import get_visible_document, parse_document
from backend.app.model_gateway import get_llm_client
from backend.app.referral.completeness import check_completeness
from backend.app.referral.evidence import align_to_pages
from backend.app.referral.extraction import model_output_schema, validate_and_normalize_referral_model_payload
from backend.app.referral.ocr_quality import evaluate_ocr_quality
from backend.app.referral.pipeline_events import record_pipeline_event
from backend.app.referral.prompts import REFERRAL_PROMPT_VERSION, REFERRAL_SYSTEM_PROMPT, build_referral_prompt
from backend.app.referral.routing import allowed_targets, enforce_allowed_routing
from backend.app.referral.schemas import ReferralAnalysis, ReferralCaseRead
from backend.app.referral.statuses import (
    PIPELINE_STAGE_MODEL,
    PIPELINE_STAGE_OCR,
    PIPELINE_STAGE_PYPDF,
    PIPELINE_STAGE_VALIDATION,
    PIPELINE_STAGE_WORKLIST,
    PIPELINE_STATUS_COMPLETED,
    PIPELINE_STATUS_FAILED,
    PIPELINE_STATUS_OK,
    PIPELINE_STATUS_STARTED,
    PIPELINE_STATUS_WARNING,
    STATUS_ANALYSIS_READY,
)
from backend.app.referral.text_extraction import apply_text_extraction_fallback
from backend.app.security.acl import require_referral_case_visible, require_referral_reviewer
from backend.app.security.auth import DemoUser


def should_require_review(analysis: ReferralAnalysis) -> bool:
    if analysis.routing_proposal.confidence < 0.6:
        return True
    if any(item.severity == "blocking" for item in analysis.missing_items):
        return True
    if not analysis.evidence:
        return True
    return analysis.human_review_required


def analyze_referral(session: Session, document_id: str, user: DemoUser) -> ReferralCaseRead:
    settings = get_settings()
    generation = effective_model_config(settings)
    require_referral_reviewer(user)
    document = get_visible_document(session, document_id, user)
    record_pipeline_event(
        session,
        stage=PIPELINE_STAGE_PYPDF,
        status=PIPELINE_STATUS_STARTED,
        message="PyPDF/Text extraction started",
        document_id=document.id,
        commit=True,
    )
    try:
        parsed = parse_document(session, document)
    except Exception as exc:
        record_pipeline_event(
            session,
            stage=PIPELINE_STAGE_PYPDF,
            status=PIPELINE_STATUS_FAILED,
            message="PyPDF/Text extraction failed",
            document_id=document.id,
            payload={"error_type": type(exc).__name__},
            commit=True,
        )
        raise
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
    if ocr_quality.status == "failed":
        ocr_event_status = PIPELINE_STATUS_FAILED
        ocr_message = f"OCR confidence {ocr_quality.min_confidence or 0:.2f}, human review required"
    elif ocr_quality.status == "low":
        ocr_event_status = PIPELINE_STATUS_WARNING
        ocr_message = f"OCR low confidence {ocr_quality.min_confidence or 0:.2f}, human review required"
    elif ocr_quality.status == "ok":
        ocr_event_status = PIPELINE_STATUS_OK
        ocr_message = f"OCR confidence {ocr_quality.min_confidence:.2f}"
    else:
        ocr_event_status = PIPELINE_STATUS_OK
        ocr_message = "OCR fallback not required"
    record_pipeline_event(
        session,
        stage=PIPELINE_STAGE_OCR,
        status=ocr_event_status,
        message=ocr_message,
        document_id=document.id,
        payload={"ocr_min_confidence": ocr_quality.min_confidence, "ocr_status": ocr_quality.status},
        commit=True,
    )
    original_character_count = len(parsed.text)
    parsed_text = parsed.text
    truncated_character_count = original_character_count
    truncation_warning = None
    if len(parsed_text) > settings.max_referral_text_chars:
        parsed_text = parsed_text[: settings.max_referral_text_chars]
        truncated_character_count = len(parsed_text)
        truncation_warning = (
            "Document text was truncated for demo model context "
            f"({original_character_count} -> {truncated_character_count} characters)."
        )
    client = get_llm_client()
    record_pipeline_event(
        session,
        stage=PIPELINE_STAGE_MODEL,
        status=PIPELINE_STATUS_STARTED,
        message="Gemma analysis started",
        document_id=document.id,
        payload={
            "model_profile": generation.model_id,
            "model_provider": generation.provider,
            "original_character_count": original_character_count,
            "model_input_character_count": truncated_character_count,
            "truncated": truncated_character_count < original_character_count,
        },
        commit=True,
    )
    model_failed = False
    try:
        raw = client.generate_json(
            system_prompt=REFERRAL_SYSTEM_PROMPT,
            user_prompt=build_referral_prompt(parsed_text, allowed_targets()),
            schema=model_output_schema(),
            temperature=0.0,
            max_tokens=settings.generation_max_tokens,
        )
        analysis = validate_and_normalize_referral_model_payload(raw, document_id=document.id)
    except Exception as exc:
        model_failed = True
        record_pipeline_event(
            session,
            stage=PIPELINE_STAGE_MODEL,
            status=PIPELINE_STATUS_FAILED,
            message="Model analysis failed, safe review case created",
            document_id=document.id,
            payload={
                "model_profile": generation.model_id,
                "model_provider": generation.provider,
                "error_type": type(exc).__name__,
            },
        )
        analysis = ReferralAnalysis(
            document_id=document.id,
            document_type="unknown",
            human_review_required=True,
            warnings=["Local model gateway failed or returned invalid JSON. Human review required."],
    )
    analysis = apply_text_extraction_fallback(analysis, parsed_text)
    analysis = enforce_allowed_routing(analysis)
    if not model_failed:
        routing_target = analysis.routing_proposal.routing_target or "unclear"
        confidence = analysis.routing_proposal.confidence
        if generation.provider == "test_double":
            model_message = "Internal test model stage completed"
        else:
            model_message = f"Model proposed {routing_target}, confidence {confidence:.2f}"
        record_pipeline_event(
            session,
            stage=PIPELINE_STAGE_MODEL,
            status=PIPELINE_STATUS_OK,
            message=model_message,
            document_id=document.id,
            payload={
                "model_profile": generation.model_id,
                "routing_target": analysis.routing_proposal.routing_target,
                "confidence": confidence,
            },
        )
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
    if truncation_warning and truncation_warning not in analysis.warnings:
        analysis.warnings.append(truncation_warning)
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
            "original_character_count": original_character_count,
            "model_input_character_count": truncated_character_count,
            "truncated": truncated_character_count < original_character_count,
        },
    )

    case = ReferralCase(
        id=uuid.uuid4().hex,
        document_id=document.id,
        status=STATUS_ANALYSIS_READY,
        analysis_json=analysis.model_dump(mode="json"),
        model_profile=generation.model_id,
        prompt_version=REFERRAL_PROMPT_VERSION,
        created_by=user.id,
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
    log_event(
        session,
        user,
        AuditPayload(
            action="referral.model_suggestion",
            object_type="referral_case",
            object_id=case.id,
            payload_json={"document_id": document.id},
            model_profile=generation.model_id,
            prompt_version=REFERRAL_PROMPT_VERSION,
            input_hash=hash_json({"document_id": document.id, "text": parsed_text}),
            output_hash=hash_json(analysis.model_dump(mode="json")),
            decision_after=analysis.model_dump(mode="json"),
        ),
        commit=False,
    )
    session.commit()
    session.refresh(case)
    return case_to_read(case)


def case_to_read(case: ReferralCase) -> ReferralCaseRead:
    return ReferralCaseRead(
        id=case.id,
        document_id=case.document_id,
        status=case.status,
        analysis=ReferralAnalysis.model_validate(case.analysis_json),
        model_profile=case.model_profile,
        prompt_version=case.prompt_version,
        created_at=case.created_at,
        reviewed_at=case.reviewed_at,
    )


def get_referral_case(session: Session, case_id: str, user: DemoUser) -> ReferralCaseRead:
    require_referral_reviewer(user)
    case = require_referral_case_visible(session, case_id, user)
    return case_to_read(case)
