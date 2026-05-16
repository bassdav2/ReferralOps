from __future__ import annotations

from pathlib import Path

from backend.app.db.models import DocumentPage
from backend.app.documents.registry import parse_document, register_file
from backend.app.referral.service import analyze_referral
from backend.app.security.auth import get_current_user


class EmptyLocalModelClient:
    def generate_json(self, **kwargs):
        return {
            "document_id": "pending",
            "document_type": "referral",
            "language": "de",
            "routing_proposal": {
                "department": None,
                "routing_target": None,
                "administrative_urgency": "human_review",
                "confidence": 1.0,
            },
            "missing_items": [],
            "evidence": [],
            "human_review_required": True,
            "warnings": [],
        }


def test_visible_referral_text_fills_admin_fields_when_local_model_misses_them(
    monkeypatch,
    session,
    tmp_path: Path,
):
    sample = tmp_path / "referral.txt"
    sample.write_text(
        "\n".join(
            [
                "Synthetische Zuweisung Kardiologie",
                "Patientin: Lea Beispiel, geboren 14.02.1978",
                "Telefon: +41 44 000 00 00",
                "Zuweisende Aerztin: Dr. Petra Demo, Praxis Demo",
                "Grund: Zuweisung wegen Thoraxbeschwerden und Dyspnoe bei Belastung.",
                "Beilagen: Labor unklar, Vorberichte unklar. Medikamentenliste fehlt.",
                "Hinweis: Demo-Daten, keine echte Patientin.",
            ]
        ),
        encoding="utf-8",
    )
    user = get_current_user("sekretariat_kardiologie")
    document = register_file(
        session,
        sample,
        title="synthetic cardiology referral",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
    )
    monkeypatch.setattr("backend.app.referral.service.get_llm_client", lambda: EmptyLocalModelClient())

    case = analyze_referral(session, document.id, user)
    analysis = case.analysis
    missing_fields = {item.field for item in analysis.missing_items}

    assert analysis.patient.name == "Lea Beispiel"
    assert analysis.patient.birth_date.isoformat() == "1978-02-14"
    assert analysis.patient.phone == "+41 44 000 00 00"
    assert analysis.referring_party.physician_name == "Dr. Petra Demo"
    assert analysis.referring_party.organization == "Praxis Demo"
    assert analysis.clinical_context_for_admin_routing.reason_for_referral.startswith(
        "Zuweisung wegen Thoraxbeschwerden"
    )
    assert analysis.routing_proposal.routing_target == "kardiologie"
    assert analysis.routing_proposal.confidence < 1.0
    assert "attachments.medication_list" in missing_fields
    assert "patient.name" not in missing_fields
    assert "patient.birth_date" not in missing_fields
    assert "patient.phone" not in missing_fields
    assert "referring_party.physician_name" not in missing_fields
    assert "clinical_context_for_admin_routing.reason_for_referral" not in missing_fields
    assert any(item.claim == "patient.name" for item in analysis.evidence)


def test_referral_analysis_uses_cached_pages_when_original_storage_is_missing(
    monkeypatch,
    session,
    tmp_path: Path,
):
    sample = tmp_path / "referral.txt"
    sample.write_text(
        "\n".join(
            [
                "Synthetische Zuweisung Kardiologie",
                "Patientin: Lea Beispiel, geboren 14.02.1978",
                "Telefon: +41 44 000 00 00",
                "Zuweisende Aerztin: Dr. Petra Demo, Praxis Demo",
                "Grund: Zuweisung wegen Thoraxbeschwerden und Dyspnoe bei Belastung.",
                "Beilagen: Labor unklar, Vorberichte unklar. Medikamentenliste fehlt.",
            ]
        ),
        encoding="utf-8",
    )
    user = get_current_user("sekretariat_kardiologie")
    document = register_file(
        session,
        sample,
        title="cached referral",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
    )
    parse_document(session, document)
    sample.unlink()
    monkeypatch.setattr("backend.app.referral.service.get_llm_client", lambda: EmptyLocalModelClient())

    case = analyze_referral(session, document.id, user)

    assert case.analysis.patient.name == "Lea Beispiel"
    assert case.analysis.routing_proposal.department == "Kardiologie"
    assert "OCR is not available" not in " ".join(case.analysis.warnings)


def test_referral_analysis_reparses_source_uri_when_upload_copy_is_missing(
    monkeypatch,
    session,
    tmp_path: Path,
):
    sample = tmp_path / "referral.txt"
    sample.write_text(
        "\n".join(
            [
                "Synthetische Zuweisung Kardiologie",
                "Patientin: Lea Beispiel, geboren 14.02.1978",
                "Telefon: +41 44 000 00 00",
                "Zuweisende Aerztin: Dr. Petra Demo, Praxis Demo",
                "Grund: Zuweisung wegen Thoraxbeschwerden und Dyspnoe bei Belastung.",
                "Beilagen: Labor unklar, Vorberichte unklar. Medikamentenliste fehlt.",
            ]
        ),
        encoding="utf-8",
    )
    user = get_current_user("sekretariat_kardiologie")
    document = register_file(
        session,
        sample,
        title="source fallback referral",
        access_groups=["referral_reviewers"],
        contains_patient_data=True,
    )
    document.storage_pointer = str(tmp_path / "missing_upload_copy.pdf")
    document.source_uri = str(sample)
    document.external_id = str(sample)
    document.parse_status = "parsed"
    session.add(
        DocumentPage(
            document_id=document.id,
            page_number=1,
            text="OCR is not available for missing_upload_copy.pdf. Human review required.",
            ocr_confidence=0.0,
        )
    )
    session.commit()
    monkeypatch.setattr("backend.app.referral.service.get_llm_client", lambda: EmptyLocalModelClient())

    case = analyze_referral(session, document.id, user)

    assert case.analysis.patient.name == "Lea Beispiel"
    assert case.analysis.routing_proposal.department == "Kardiologie"
    assert "OCR is not available" not in " ".join(case.analysis.warnings)
