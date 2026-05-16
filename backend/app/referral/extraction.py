from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from backend.app.referral.schemas import (
    ClinicalContext,
    CompactReferralModelOutput,
    EvidenceItem,
    ModelSuggestedDestination,
    ReferralAnalysis,
    RoutingProposal,
    SecondaryRoutingSuggestion,
    UnmappedFinding,
)

MODEL_SCHEMA_WARNING = "Model response did not validate against compact ReferralModelOutput schema."
FULL_SCHEMA_WARNING = "Model response did not validate against ReferralAnalysis schema."


def model_output_schema() -> dict[str, Any]:
    return CompactReferralModelOutput.model_json_schema()


def _fallback_analysis(
    document_id: str,
    warning: str,
    *,
    validation_error: ValidationError | None = None,
) -> ReferralAnalysis:
    warnings = [warning]
    if validation_error is not None:
        error_types = sorted({str(error.get("type")) for error in validation_error.errors()[:5]})
        if error_types:
            warnings.append(f"Validation error types: {', '.join(error_types)}.")
    return ReferralAnalysis(
        document_id=document_id,
        document_type="unknown",
        human_review_required=True,
        warnings=warnings,
    )


def validate_referral_model_payload(payload: Any) -> CompactReferralModelOutput:
    if not isinstance(payload, dict):
        raise ValueError("Model response must be a JSON object.")
    return CompactReferralModelOutput.model_validate(payload)


def normalize_model_output_to_referral_analysis(
    payload: CompactReferralModelOutput,
    *,
    document_id: str,
) -> ReferralAnalysis:
    evidence = [
        EvidenceItem(
            claim=item.field,
            quote=item.quote,
            source_span="model_output",
        )
        for item in payload.evidence
    ]
    secondary = [
        SecondaryRoutingSuggestion(routing_target=target, label=target, reason="Model secondary routing candidate.")
        for target in payload.secondary_routing_targets
    ]
    unmapped = [
        UnmappedFinding(label="missing_required_item", value=item, reason="Model reported a missing required item.")
        for item in payload.missing_required_items
    ]
    if payload.rationale:
        unmapped.append(
            UnmappedFinding(
                label="model_rationale",
                value=payload.rationale,
                reason="Short model-facing rationale retained for auditability.",
            )
        )
    if payload.model_suggested_destination:
        unmapped.append(
            UnmappedFinding(
                label="model_suggested_destination",
                value=payload.model_suggested_destination,
                reason="Free-text destination suggestion; forwarding still uses controlled routing_target.",
            )
        )
    warnings = [f"Model uncertainty: {item}" for item in payload.uncertainties]

    return ReferralAnalysis(
        document_id=document_id,
        document_type=payload.document_type,
        language=payload.language,
        patient=payload.patient,
        referring_party=payload.referring_party,
        clinical_context_for_admin_routing=ClinicalContext(
            reason_for_referral=payload.clinical_context.reason_for_referral,
            suspected_or_known_conditions=payload.clinical_context.conditions,
            symptoms=payload.clinical_context.symptoms,
            medication_list_mentioned=payload.clinical_context.medication_list_mentioned,
            lab_or_imaging_mentioned=payload.clinical_context.lab_or_imaging_mentioned,
            requested_service=payload.clinical_context.requested_service,
        ),
        attachments=payload.attachments,
        routing_proposal=RoutingProposal(
            routing_target=payload.routing.target,
            administrative_urgency=payload.routing.administrative_urgency,
            confidence=payload.routing.confidence,
        ),
        model_suggested_destination=(
            ModelSuggestedDestination(
                label=payload.model_suggested_destination,
                reason=payload.rationale,
                confidence=payload.routing.confidence,
            )
            if payload.model_suggested_destination
            else None
        ),
        secondary_routing_targets=secondary,
        unmapped_findings=unmapped,
        evidence=evidence,
        human_review_required=payload.human_review_required,
        warnings=warnings,
    )


def validate_and_normalize_referral_model_payload(payload: Any, *, document_id: str) -> ReferralAnalysis:
    if isinstance(payload, dict) and (
        "routing_proposal" in payload or "clinical_context_for_admin_routing" in payload
    ):
        full_payload = dict(payload)
        full_payload["document_id"] = document_id
        return validate_referral_payload(full_payload)
    try:
        compact = validate_referral_model_payload(payload)
    except ValidationError as exc:
        return _fallback_analysis(document_id, MODEL_SCHEMA_WARNING, validation_error=exc)
    except Exception:
        return _fallback_analysis(document_id, "Model response was not a valid compact referral JSON object.")
    return normalize_model_output_to_referral_analysis(compact, document_id=document_id)


def validate_referral_payload(payload: Any) -> ReferralAnalysis:
    if not isinstance(payload, dict):
        return _fallback_analysis("unknown", FULL_SCHEMA_WARNING)
    try:
        return ReferralAnalysis.model_validate(payload)
    except ValidationError as exc:
        return _fallback_analysis(payload.get("document_id", "unknown"), FULL_SCHEMA_WARNING, validation_error=exc)
