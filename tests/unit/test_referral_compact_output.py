from __future__ import annotations

from backend.app.referral.extraction import (
    validate_and_normalize_referral_model_payload,
    validate_referral_payload,
)
from backend.app.referral.routing import enforce_allowed_routing


def test_compact_model_output_normalizes_to_full_referral_analysis():
    analysis = validate_and_normalize_referral_model_payload(
        {
            "document_type": "referral",
            "language": "de",
            "patient": {"name": "Demo Patient", "birth_date": "1978-02-14", "sex": "female"},
            "referring_party": {"physician_name": "Dr. Demo", "organization": "Praxis Demo"},
            "clinical_context": {
                "reason_for_referral": "Administrative CT-Anmeldung.",
                "conditions": ["Demo condition"],
                "symptoms": ["Demo symptom"],
                "requested_service": "CT",
                "medication_list_mentioned": False,
                "lab_or_imaging_mentioned": True,
            },
            "attachments": {"lab": "present", "imaging": "present", "medication_list": "unclear"},
            "routing": {"target": "radiologie", "confidence": 0.8, "administrative_urgency": "normal"},
            "secondary_routing_targets": ["kardiologie"],
            "model_suggested_destination": "Radiologie CT Anmeldung",
            "missing_required_items": ["attachments.medication_list"],
            "evidence": [{"field": "routing", "quote": "CT-Anmeldung"}],
            "rationale": "Administrative routing only.",
            "uncertainties": ["Medication list unclear"],
            "human_review_required": True,
        },
        document_id="doc-1",
    )

    assert analysis.document_id == "doc-1"
    assert analysis.model_suggested_destination is not None
    assert analysis.model_suggested_destination.label == "Radiologie CT Anmeldung"
    assert analysis.routing_proposal.routing_target == "radiologie"
    assert analysis.clinical_context_for_admin_routing.requested_service == "CT"
    assert analysis.secondary_routing_targets[0].routing_target == "kardiologie"
    assert analysis.evidence[0].source_span == "model_output"
    assert "Medication list unclear" in analysis.warnings[0]


def test_invalid_compact_payload_returns_auditable_safe_fallback():
    analysis = validate_and_normalize_referral_model_payload(
        {"routing": {"target": "radiologie", "confidence": 2.0}},
        document_id="doc-2",
    )

    assert analysis.document_id == "doc-2"
    assert analysis.routing_proposal.routing_target is None
    assert analysis.human_review_required is True
    assert any("did not validate" in warning for warning in analysis.warnings)


def test_validate_referral_payload_handles_non_dict_payload():
    analysis = validate_referral_payload(None)

    assert analysis.document_id == "unknown"
    assert analysis.human_review_required is True
    assert any("did not validate" in warning for warning in analysis.warnings)


def test_routing_alias_normalization_maps_display_name(isolated_project_root):
    analysis = validate_and_normalize_referral_model_payload(
        {
            "document_type": "referral",
            "routing": {"target": "Radiologie", "confidence": 0.7, "administrative_urgency": "normal"},
        },
        document_id="doc-3",
    )

    enforced = enforce_allowed_routing(analysis)

    assert enforced.routing_proposal.routing_target == "radiologie"
    assert enforced.routing_proposal.department == "Radiologie"


def test_free_text_destination_can_map_when_primary_target_is_empty(isolated_project_root):
    analysis = validate_and_normalize_referral_model_payload(
        {
            "document_type": "referral",
            "model_suggested_destination": "Notfallnahe Abklärung",
            "routing": {"target": None, "confidence": 0.66, "administrative_urgency": "human_review"},
            "secondary_routing_targets": ["Allgemeinambulanz", "Pflegekoordination"],
        },
        document_id="doc-4",
    )

    enforced = enforce_allowed_routing(analysis)

    assert enforced.routing_proposal.routing_target == "notfallnahe_abklaerung"
    assert enforced.model_suggested_destination is not None
    assert enforced.model_suggested_destination.mapped_to_routing_target == "notfallnahe_abklaerung"
    assert [item.routing_target for item in enforced.secondary_routing_targets] == [
        "allgemeinambulanz",
        "pflegekoordination",
    ]
