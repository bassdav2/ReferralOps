from __future__ import annotations

import hashlib
import math
import re

from backend.app.model_gateway.embedding_client import EmbeddingClient


def _first_chunk_id_for_title(prompt: str, title_hint: str) -> str | None:
    current_chunk_id = None
    lines = prompt.splitlines()
    for line in lines:
        lowered = line.lower()
        source_match = re.search(r'<source[^>]*id="([^"]+)"[^>]*title="([^"]*)"', lowered)
        if source_match and title_hint.lower() in source_match.group(2):
            return source_match.group(1)
        if lowered.startswith("source_id="):
            current_chunk_id = line.split("=", 1)[1].strip()
        elif lowered.startswith("title=") and title_hint.lower() in lowered:
            return current_chunk_id
        if line.startswith("[") and title_hint.lower() in lowered:
            return line.split("]", 1)[0].strip("[")
    return None


def _guideline_response(prompt: str) -> dict:
    question = prompt.lower()
    chunk_id = None
    if "kis-zugang" in question or "kis zugang" in question:
        answer = (
            "Ein KIS-Zugang wird ueber das IT-Serviceportal beantragt "
            "und durch die vorgesetzte Person freigegeben."
        )
        chunk_id = _first_chunk_id_for_title(prompt, "it access")
    elif "nadelstich" in question:
        answer = (
            "Nach einer Nadelstichverletzung sind Wundversorgung, Meldung "
            "und Kontakt mit Hygiene oder Arbeitsmedizin vorgesehen."
        )
        chunk_id = _first_chunk_id_for_title(prompt, "hygiene nadelstich")
    elif "pflichtschulung" in question or "eintritt" in question:
        answer = (
            "Beim Eintritt sind Datenschutz, Informationssicherheit, Hygiene "
            "und KIS-Grundlagen als Pflichtschulungen vorgesehen."
        )
        chunk_id = _first_chunk_id_for_title(prompt, "onboarding checklist")
    elif "automatisch ins dms" in question or "dms schreiben" in question:
        answer = "KI-Vorschlaege duerfen nur nach menschlicher Freigabe ins DMS geschrieben werden."
        chunk_id = _first_chunk_id_for_title(prompt, "dms writeback")
    else:
        return {
            "answer": "Ich finde dazu in den verfuegbaren internen Quellen keine verlaessliche Antwort.",
            "confidence": "no_answer",
            "sources": [],
            "limitations": "Keine ausreichende lokale Quelle.",
            "escalation_required": True,
            "escalation_contact": None,
            "safety_flags": ["no_answer"],
        }

    return {
        "answer": answer,
        "confidence": "high",
        "sources": [
            {
                "document_id": "test-double",
                "title": "test-double",
                "version": "test-v1",
                "chunk_id": chunk_id,
                "page": None,
                "quote": answer[:120],
            }
        ] if chunk_id else [],
        "limitations": None,
        "escalation_required": False,
        "escalation_contact": None,
        "safety_flags": [],
    }


def _referral_response(prompt: str) -> dict:
    base = {
        "document_id": "pending",
        "document_type": "referral",
        "language": "de",
        "patient": {
            "name": "Lea Beispiel",
            "birth_date": "1978-02-14",
            "sex": "female",
            "phone": "+41 44 000 00 00",
            "insurance_id": None,
            "address": "Demoallee 10, 8000 Zuerich",
        },
        "referring_party": {
            "physician_name": "Dr. Petra Demo",
            "organization": "Praxis Demo",
            "phone": "+41 44 111 22 33",
            "email": "praxis@example.invalid",
            "zsr_or_gln": None,
        },
        "clinical_context_for_admin_routing": {
            "reason_for_referral": "Administrative Vorbereitung einer fachlichen Abklaerung.",
            "suspected_or_known_conditions": [],
            "symptoms": [],
            "medication_list_mentioned": False,
            "lab_or_imaging_mentioned": False,
            "requested_service": None,
        },
        "attachments": {
            "lab": "unclear",
            "imaging": "unclear",
            "medication_list": "missing",
            "prior_reports": "unclear",
            "consent_form": "unclear",
        },
        "routing_proposal": {
            "department": "Innere Medizin",
            "routing_target": "innere_medizin",
            "administrative_urgency": "human_review",
            "confidence": 0.65,
        },
        "missing_items": [],
        "evidence": [],
        "human_review_required": True,
        "warnings": [],
    }

    if "thorax" in prompt or "dyspnoe" in prompt or "synkope" in prompt:
        base["clinical_context_for_admin_routing"].update(
            {
                "reason_for_referral": "Thoraxbeschwerden, Dyspnoe oder Synkope.",
                "symptoms": ["Thoraxbeschwerden", "Dyspnoe"],
            }
        )
        base["routing_proposal"] = {
            "department": "Kardiologie",
            "routing_target": "kardiologie",
            "administrative_urgency": "timely",
            "confidence": 0.82,
        }
        base["evidence"] = [
            {
                "claim": "Kardiologie-Vorschlag",
                "quote": "Zuweisung wegen Thoraxbeschwerden und Dyspnoe.",
                "page": 1,
                "source_span": "test-double",
            }
        ]
        base["human_review_required"] = False
    elif "mri" in prompt or "ct " in prompt or "bildgebung" in prompt:
        base["clinical_context_for_admin_routing"].update(
            {
                "reason_for_referral": "Bildgebung wurde angefragt.",
                "requested_service": "Bildgebung",
                "lab_or_imaging_mentioned": True,
            }
        )
        base["attachments"].update(
            {
                "lab": "present",
                "imaging": "present",
                "medication_list": "present",
                "prior_reports": "present",
            }
        )
        base["routing_proposal"] = {
            "department": "Radiologie",
            "routing_target": "radiologie",
            "administrative_urgency": "normal",
            "confidence": 0.88,
        }
        base["evidence"] = [
            {
                "claim": "Radiologie-Zuweisung",
                "quote": "Gewuenscht ist eine Bildgebung.",
                "page": 1,
                "source_span": "test-double",
            }
        ]
        base["human_review_required"] = False
    elif "unterbauch" in prompt or "gynäkologie" in prompt or "gynäkologisch" in prompt:
        base["clinical_context_for_admin_routing"].update(
            {
                "reason_for_referral": "Unterbauchschmerz, gynaekologische Abklaerung moeglich.",
                "symptoms": ["Unterbauchschmerz"],
            }
        )
        base["routing_proposal"] = {
            "department": "Gynaekologie",
            "routing_target": "gynaekologie",
            "administrative_urgency": "human_review",
            "confidence": 0.62,
        }
        base["evidence"] = [
            {
                "claim": "Gynaekologie-Vorschlag",
                "quote": "Unterbauchschmerz, bitte geeignete Sprechstunde pruefen.",
                "page": 1,
                "source_span": "test-double",
            }
        ]
    elif "innere medizin" in prompt or "gewichtsabnahme" in prompt or "muedigkeit" in prompt:
        base["clinical_context_for_admin_routing"].update(
            {
                "reason_for_referral": "Internistische Abklaerung bei Muedigkeit und Gewichtsabnahme.",
                "symptoms": ["Muedigkeit", "Gewichtsabnahme"],
            }
        )
        base["routing_proposal"] = {
            "department": "Innere Medizin",
            "routing_target": "innere_medizin",
            "administrative_urgency": "normal",
            "confidence": 0.86,
        }
        base["evidence"] = [
            {
                "claim": "Innere-Medizin-Zuweisung",
                "quote": "Zuweisung Innere Medizin mit Muedigkeit und Gewichtsabnahme.",
                "page": 1,
                "source_span": "test-double",
            }
        ]
        base["human_review_required"] = True
    return base


class TestDoubleLLMClient:
    model_version = "test-double-local-v1"

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> dict:
        prompt = f"{system_prompt}\n{user_prompt}".lower()
        schema_hint = str(schema).lower()
        if "guidelineanswer" in schema_hint or "richtlinien-assistent" in prompt:
            return _guideline_response(prompt)
        if "referralanalysis" in schema_hint or "zuweisung" in prompt:
            return _referral_response(prompt)
        return _guideline_response(prompt)


class TestDoubleEmbeddingClient(EmbeddingClient):
    dimensions = 48

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in re.findall(r"[a-zA-ZäöüÄÖÜß0-9]+", text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = digest[0] % self.dimensions
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

# Compatibility aliases for existing unit tests after the public provider name was cleaned up.
test_guideline_response = _guideline_response
test_referral_response = _referral_response
