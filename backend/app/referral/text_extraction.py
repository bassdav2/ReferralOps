from __future__ import annotations

import re
from datetime import date

from backend.app.referral.routing import canonical_routing_target, load_routing_taxonomy
from backend.app.referral.schemas import EvidenceItem, ReferralAnalysis

_DATE_RE = re.compile(
    r"(?P<day>\d{1,2})[.\-/](?P<month>\d{1,2})[.\-/](?P<year>\d{2,4})|"
    r"(?P<iso>\d{4}-\d{2}-\d{2})"
)
_PHONE_RE = re.compile(r"\+?\d[\d\s()./-]{5,}\d")
_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_INSURANCE_ID_RE = re.compile(r"\bSYN-INS-[A-Z0-9-]+\b", re.IGNORECASE)
_GLN_ZSR_RE = re.compile(r"\b(?:GLN|ZSR)-?[A-Z0-9-]*\d[A-Z0-9-]*\b", re.IGNORECASE)


def _blank(value: object) -> bool:
    return value is None or value == "" or value == []


def _clean(value: str) -> str:
    return " ".join(value.strip(" \t:;,.").split())


def _parse_date(raw: str) -> date | None:
    match = _DATE_RE.search(raw)
    if not match:
        return None
    if match.group("iso"):
        try:
            return date.fromisoformat(match.group("iso"))
        except ValueError:
            return None

    year = int(match.group("year"))
    if year < 100:
        year += 1900 if year >= 30 else 2000
    try:
        return date(year, int(match.group("month")), int(match.group("day")))
    except ValueError:
        return None


def _first_match_line(lines: list[str], pattern: str) -> tuple[re.Match[str], str] | None:
    compiled = re.compile(pattern, re.IGNORECASE)
    for line in lines:
        match = compiled.search(line)
        if match:
            return match, line
    return None


def _first_phone(text: str) -> str | None:
    match = _PHONE_RE.search(text)
    return _clean(match.group(0)) if match else None


def _first_email(text: str) -> str | None:
    match = _EMAIL_RE.search(text)
    return _clean(match.group(0)) if match else None


def _first_insurance_id(text: str) -> str | None:
    match = _INSURANCE_ID_RE.search(text)
    return _clean(match.group(0).upper()) if match else None


def _first_gln_zsr(text: str) -> str | None:
    match = _GLN_ZSR_RE.search(text)
    return _clean(match.group(0).upper()) if match else None


def _looks_like_phone(value: str) -> bool:
    lowered = value.lower()
    if "gln" in lowered or "zsr" in lowered or "syn-" in lowered:
        return False
    return _first_phone(value) is not None


def _is_likely_label(line: str) -> bool:
    lowered = line.lower().rstrip(":")
    if not lowered:
        return False
    prefix = lowered.split(":", 1)[0].strip()
    label_markers = (
        "adresse",
        "beilagen",
        "e-mail",
        "email",
        "fachrichtung",
        "fallnummer",
        "geburtsdatum",
        "geschlecht",
        "gln/zsr",
        "grund",
        "klinische angaben",
        "name",
        "organisation",
        "patientendaten",
        "patienten-id",
        "telefon patient",
        "telefon zuweiser",
        "versicherungsnummer",
        "zuweisende aerztin/arzt",
        "zuweisende ärztin/arzt",
        "zuweisende stelle",
    )
    return (
        lowered in label_markers
        or prefix in label_markers
        or (line.endswith(":") and any(marker in lowered for marker in label_markers))
    )


def _looks_like_name(value: str) -> bool:
    cleaned = _clean(value)
    if not cleaned or _is_likely_label(cleaned):
        return False
    if ":" in cleaned:
        return False
    lowered = cleaned.lower()
    if "syn-" in lowered or "@" in cleaned or _first_phone(cleaned) or _parse_date(cleaned):
        return False
    return bool(re.search(r"[a-zäöüß]+(?:,\s*|\s+)[a-zäöüß]+", cleaned, flags=re.IGNORECASE))


def _looks_like_physician(value: str) -> bool:
    cleaned = _clean(value)
    if not cleaned or _is_likely_label(cleaned):
        return False
    return bool(re.search(r"\b(?:dr\.?|prof\.?|med\.)\b", cleaned, flags=re.IGNORECASE))


def _looks_like_organization(value: str) -> bool:
    cleaned = _clean(value)
    if not cleaned or _is_likely_label(cleaned):
        return False
    if _looks_like_physician(cleaned) or _first_email(cleaned) or _first_phone(cleaned) or _first_gln_zsr(cleaned):
        return False
    lowered = cleaned.lower()
    if lowered.startswith("syn-") or _parse_date(cleaned):
        return False
    org_markers = ("praxis", "spital", "zentrum", "labor", "klinik", "hausarzt", "pflege", "netz", "institut")
    return any(marker in lowered for marker in org_markers)


def _first_labeled_value(
    lines: list[str],
    pattern: str,
    *,
    predicate=None,
    lookahead: int = 0,
) -> tuple[str, str] | None:
    compiled = re.compile(pattern, re.IGNORECASE)
    for index, line in enumerate(lines):
        match = compiled.search(line)
        if not match:
            continue
        raw_value = match.groupdict().get("value")
        if raw_value is None and ":" in line:
            raw_value = line.split(":", 1)[1]
        value = _clean(raw_value or "")
        if value and (predicate is None or predicate(value)):
            return value, line
        for candidate_line in lines[index + 1 : index + 1 + lookahead]:
            candidate = _clean(candidate_line)
            if not candidate:
                continue
            if predicate is not None and not predicate(candidate):
                continue
            return candidate, line
    return None


def _add_evidence(analysis: ReferralAnalysis, claim: str, quote: str) -> None:
    quote = _clean(quote)
    if not quote:
        return
    if any(item.claim == claim and item.quote == quote for item in analysis.evidence):
        return
    analysis.evidence.append(EvidenceItem(claim=claim, quote=quote, page=None, source_span="text_extraction"))


def _add_warning(analysis: ReferralAnalysis, warning: str) -> None:
    if warning not in analysis.warnings:
        analysis.warnings.append(warning)


def _split_patient_line(value: str) -> tuple[str | None, date | None]:
    birth_date = _parse_date(value)
    name_part = re.split(r",?\s*(?:geboren|geb\.?|geburtsdatum)\b", value, maxsplit=1, flags=re.IGNORECASE)[0]
    name = _clean(name_part)
    return (name or None), birth_date


def _merge_patient(analysis: ReferralAnalysis, lines: list[str]) -> bool:
    changed = False
    patient_line = _first_match_line(lines, r"^(?:patient|patientin)\s*:\s*(?P<value>.+)")
    if patient_line:
        match, line = patient_line
        name, birth_date = _split_patient_line(match.group("value"))
        if _blank(analysis.patient.name) and name:
            analysis.patient.name = name
            _add_evidence(analysis, "patient.name", line)
            changed = True
        if analysis.patient.birth_date is None and birth_date:
            analysis.patient.birth_date = birth_date
            _add_evidence(analysis, "patient.birth_date", line)
            changed = True

    if _blank(analysis.patient.name):
        name_value = _first_labeled_value(lines, r"^name\s*:?\s*(?P<value>.*)", predicate=_looks_like_name, lookahead=8)
        if name_value:
            value, line = name_value
            analysis.patient.name = value
            _add_evidence(analysis, "patient.name", line)
            changed = True

    if analysis.patient.birth_date is None:
        birth_line = _first_match_line(lines, r"\b(?:geboren|geb\.?|geburtsdatum)\b.*")
        if birth_line:
            _, line = birth_line
            birth_date = _parse_date(line)
            if birth_date:
                analysis.patient.birth_date = birth_date
                _add_evidence(analysis, "patient.birth_date", line)
                changed = True
        if analysis.patient.birth_date is None:
            birth_value = _first_labeled_value(
                lines,
                r"^geburtsdatum\s*:?\s*(?P<value>.*)",
                predicate=lambda value: _parse_date(value) is not None,
                lookahead=8,
            )
            if birth_value:
                value, line = birth_value
                analysis.patient.birth_date = _parse_date(value)
                _add_evidence(analysis, "patient.birth_date", line)
                changed = True

    if _blank(analysis.patient.phone):
        phone_line = _first_labeled_value(
            lines,
            r"\b(?:telefon\s+patient|patient(?:en)?[-\s]*telefon|telefon|tel\.?)\s*:\s*(?P<value>.*)",
            predicate=_looks_like_phone,
            lookahead=1,
        )
        if phone_line:
            value, line = phone_line
            phone = _first_phone(value)
            if phone:
                analysis.patient.phone = phone
                _add_evidence(analysis, "patient.phone", line)
                changed = True
    if _blank(analysis.patient.insurance_id):
        insurance_value = _first_labeled_value(
            lines,
            r"\bversicherungsnummer\s*:?\s*(?P<value>.*)",
            predicate=lambda value: _first_insurance_id(value) is not None,
            lookahead=12,
        )
        insurance_id = (
            _first_insurance_id(insurance_value[0])
            if insurance_value
            else _first_insurance_id("\n".join(lines))
        )
        if insurance_id:
            analysis.patient.insurance_id = insurance_id
            _add_evidence(analysis, "patient.insurance_id", insurance_value[1] if insurance_value else insurance_id)
            changed = True
    return changed


def _merge_referring_party(analysis: ReferralAnalysis, lines: list[str]) -> bool:
    changed = False
    referral_line = _first_match_line(
        lines,
        r"\bzuweisend(?:e|er|es|en)?\s+"
        r"(?:ärztin\s*/\s*arzt|aerztin\s*/\s*arzt|ärztin|aerztin|arzt|stelle|praxis|institution)"
        r"\s*:\s*(?P<value>.+)",
    )
    if referral_line:
        match, line = referral_line
        value = _clean(match.group("value"))
        parts = [_clean(part) for part in value.split(",") if _clean(part)]
        physician = parts[0] if parts else value
        organization = parts[1] if len(parts) > 1 else None

        if _blank(analysis.referring_party.physician_name) and physician and _looks_like_physician(physician):
            analysis.referring_party.physician_name = physician
            _add_evidence(analysis, "referring_party.physician_name", line)
            changed = True
        if _blank(analysis.referring_party.organization) and organization:
            analysis.referring_party.organization = organization
            _add_evidence(analysis, "referring_party.organization", line)
            changed = True
        if _blank(analysis.referring_party.phone):
            phone = _first_phone(value)
            if phone:
                analysis.referring_party.phone = phone
                _add_evidence(analysis, "referring_party.phone", line)
                changed = True

    if _blank(analysis.referring_party.physician_name):
        physician_value = _first_labeled_value(
            lines,
            r"\bzuweisend(?:e|er|es|en)?\s+"
            r"(?:ärztin\s*/\s*arzt|aerztin\s*/\s*arzt|ärztin|aerztin|arzt)"
            r"\s*:?\s*(?P<value>.*)",
            predicate=_looks_like_physician,
            lookahead=12,
        )
        if physician_value:
            value, line = physician_value
            analysis.referring_party.physician_name = value
            _add_evidence(analysis, "referring_party.physician_name", line)
            changed = True

    if _blank(analysis.referring_party.organization):
        organization_value = _first_labeled_value(
            lines,
            r"\b(?:organisation|praxis|institution|zuweisend(?:e|er|es|en)?\s+stelle)\s*:?\s*(?P<value>.*)",
            predicate=_looks_like_organization,
            lookahead=12,
        )
        if organization_value:
            value, line = organization_value
            analysis.referring_party.organization = value
            _add_evidence(analysis, "referring_party.organization", line)
            changed = True

    if _blank(analysis.referring_party.email):
        email_value = _first_labeled_value(
            lines,
            r"\b(?:e-mail|email)\s*:?\s*(?P<value>.*)",
            predicate=lambda value: _first_email(value) is not None,
            lookahead=12,
        )
        email = _first_email(email_value[0]) if email_value else None
        if email:
            analysis.referring_party.email = email
            _add_evidence(analysis, "referring_party.email", email_value[1])
            changed = True

    if _blank(analysis.referring_party.phone):
        phone_value = _first_labeled_value(
            lines,
            r"\b(?:telefon\s+zuweiser|telefon\s+praxis|telefon\s+zuweisend(?:e|er|es|en)?)"
            r"\s*:?\s*(?P<value>.*)",
            predicate=_looks_like_phone,
            lookahead=6,
        )
        phone = _first_phone(phone_value[0]) if phone_value else None
        if phone:
            analysis.referring_party.phone = phone
            _add_evidence(analysis, "referring_party.phone", phone_value[1])
            changed = True

    if _blank(analysis.referring_party.zsr_or_gln):
        gln_value = _first_labeled_value(
            lines,
            r"\b(?:gln\s*/\s*zsr|gln|zsr)\s*:?\s*(?P<value>.*)",
            predicate=lambda value: _first_gln_zsr(value) is not None,
            lookahead=12,
        )
        gln = _first_gln_zsr(gln_value[0]) if gln_value else None
        if gln:
            analysis.referring_party.zsr_or_gln = gln
            _add_evidence(analysis, "referring_party.zsr_or_gln", gln_value[1])
            changed = True
    return changed


def _merge_clinical_context(analysis: ReferralAnalysis, lines: list[str], text: str) -> bool:
    changed = False
    reason_line = _first_match_line(
        lines,
        r"\b(?:grund(?:\s+der\s+zuweisung)?|fragestellung|klinische angaben)\s*:\s*(?P<value>.+)",
    )
    if not reason_line:
        reason_line = _first_match_line(lines, r"\b(?P<value>zuweisung wegen .+)")
    if reason_line and _blank(analysis.clinical_context_for_admin_routing.reason_for_referral):
        match, line = reason_line
        reason = _clean(match.group("value"))
        if reason:
            analysis.clinical_context_for_admin_routing.reason_for_referral = reason
            _add_evidence(analysis, "clinical_context_for_admin_routing.reason_for_referral", line)
            changed = True

    service_line = _first_match_line(
        lines,
        r"\b(?:gewuenscht ist|gewünscht ist|untersuchung)\s*:?\s*(?P<value>.+)",
    )
    if service_line and _blank(analysis.clinical_context_for_admin_routing.requested_service):
        match, line = service_line
        value = _clean(match.group("value"))
        if value:
            analysis.clinical_context_for_admin_routing.requested_service = value
            _add_evidence(analysis, "clinical_context_for_admin_routing.requested_service", line)
            changed = True

    lowered = text.lower()
    if "medikamentenliste" in lowered and not analysis.clinical_context_for_admin_routing.medication_list_mentioned:
        analysis.clinical_context_for_admin_routing.medication_list_mentioned = True
        changed = True
    if any(term in lowered for term in ("labor", "mri", "ct ", "bildgebung", "sonographie", "roentgen", "röntgen")):
        if not analysis.clinical_context_for_admin_routing.lab_or_imaging_mentioned:
            analysis.clinical_context_for_admin_routing.lab_or_imaging_mentioned = True
            changed = True
    return changed


def _status_for(text: str, terms: tuple[str, ...]) -> str | None:
    for term in terms:
        windows = re.findall(rf".{{0,45}}{re.escape(term)}.{{0,45}}", text, flags=re.IGNORECASE)
        for window in windows:
            lowered = window.lower()
            missing_markers = ("fehlt", "fehlen", "nicht beigelegt", "nicht erwaehnt", "nicht erwähnt")
            if any(marker in lowered for marker in missing_markers):
                return "missing"
            if "unklar" in lowered:
                return "unclear"
            if any(marker in lowered for marker in ("vorhanden", "beigelegt", "liegt bei", "liegen bei")):
                return "present"
    return None


def _merge_attachments(analysis: ReferralAnalysis, text: str) -> bool:
    changed = False
    checks = {
        "lab": ("labor", "laborwerte"),
        "imaging": ("bildgebung", "mri", "ct", "sonographie", "roentgen", "röntgen"),
        "medication_list": ("medikamentenliste", "medikationsliste"),
        "prior_reports": ("vorbericht", "vorberichte", "bericht"),
        "consent_form": ("einverstaendnis", "einverständnis", "consent"),
    }
    for field, terms in checks.items():
        status = _status_for(text, terms)
        if status and getattr(analysis.attachments, field) == "unclear":
            setattr(analysis.attachments, field, status)
            changed = True
    return changed


def _contains_term(text: str, term: str) -> bool:
    term = term.strip().lower()
    if not term:
        return False
    parts = [re.escape(part) for part in re.split(r"[\s_-]+", term) if part]
    if not parts:
        return False
    escaped = r"[\s_-]+".join(parts)
    return re.search(rf"(?<!\w){escaped}(?!\w)", text, flags=re.IGNORECASE) is not None


def _routing_candidate_terms(target: str, metadata: dict) -> tuple[list[str], list[str]]:
    strong_terms = [target]
    for field in ("display_name", "department"):
        value = metadata.get(field)
        if value:
            strong_terms.append(str(value))
    strong_terms.extend(str(alias) for alias in metadata.get("aliases", []))
    keyword_terms = [str(keyword) for keyword in metadata.get("allowed_keywords", [])]
    return strong_terms, keyword_terms


def _department_for_target(target: str) -> str:
    metadata = load_routing_taxonomy()["routing_targets"].get(target, {})
    return str(metadata.get("display_name") or metadata.get("department") or target)


def _target_from_snippet(snippet: str, *, include_keywords: bool = False) -> str | None:
    direct = canonical_routing_target(snippet)
    if direct:
        return direct

    matches: list[tuple[int, str]] = []
    for target, metadata in load_routing_taxonomy()["routing_targets"].items():
        strong_terms, keyword_terms = _routing_candidate_terms(target, metadata)
        terms = strong_terms + (keyword_terms if include_keywords else [])
        for term in terms:
            if _contains_term(snippet, term):
                matches.append((len(term), target))
    if not matches:
        return None
    matches.sort(reverse=True)
    best_length = matches[0][0]
    best_targets = {target for length, target in matches if length == best_length}
    return matches[0][1] if len(best_targets) == 1 else None


_EXPLICIT_ROUTE_PATTERNS = (
    re.compile(r"\bfachrichtung\s*:?\s*(?P<value>[^.;|·]+)", re.IGNORECASE),
    re.compile(r"\bdokumenttyp\s*:?\s*(?P<value>[^.;|·]+)", re.IGNORECASE),
    re.compile(r"\bbetreff\s*:?\s*(?P<value>[^.;|·]+)", re.IGNORECASE),
    re.compile(r"\b(?:bereich|dienst)\s+[\"'“](?P<value>[^\"'”]+)[\"'”]", re.IGNORECASE),
    re.compile(r"\bbereich\s+(?P<value>[a-zäöüß -]+?)\s+zur administrativen", re.IGNORECASE),
    re.compile(r"\b(?:anmeldung|konsilanfrage)\s+(?P<value>[a-zäöüß -]+)", re.IGNORECASE),
    re.compile(r"\bzuweisung\s+(?!wegen\b)(?P<value>[a-zäöüß -]+)", re.IGNORECASE),
)

_ROUTING_HINT_MARKERS = (
    "routing-hinweis",
    "administrativer routing",
    "bitte dokument",
    "fachrichtung",
    "dokumenttyp",
    "betreff",
    "anmeldung",
    "konsilanfrage",
)

_ROUTING_NEGATIVE_MARKERS = (
    "absender",
    "sender",
    "zuweisende stelle",
    "vorversorger",
    "e-mail",
    "email",
    "beilage",
    "beilagen",
    "attachment",
    "attachments",
    "vom absender erwähnt",
    "erwähnt:",
    "erwaehnt:",
    "dringlichkeit",
    "urgency",
    "radiologiebeilage",
    "laborbeilage",
    "vorbefund",
    "vorbericht",
)


def _line_is_negative_routing_context(line: str) -> bool:
    lowered = line.lower()
    if "fachrichtung" in lowered:
        return False
    return any(marker in lowered for marker in _ROUTING_NEGATIVE_MARKERS)


def _explicit_routing_from_lines(lines: list[str]) -> tuple[str, str] | None:
    candidates: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines[:30]):
        lowered = line.lower()
        snippets: list[str] = []
        for pattern in _EXPLICIT_ROUTE_PATTERNS:
            for match in pattern.finditer(line):
                snippets.append(match.group("value"))
        if any(marker in lowered for marker in _ROUTING_HINT_MARKERS):
            snippets.append(line)
            if index + 1 < len(lines):
                snippets.append(lines[index + 1])
        if _line_is_negative_routing_context(line) and "fachrichtung" not in lowered:
            continue
        for snippet in snippets:
            target = _target_from_snippet(snippet)
            if target:
                priority = 100 - index
                if "fachrichtung" in lowered:
                    priority += 100
                if "routing-hinweis" in lowered or "bitte dokument" in lowered:
                    priority += 80
                candidates.append((priority, target, line))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1], candidates[0][2]


def _infer_routing_from_lines(lines: list[str]) -> tuple[str, str, float] | None:
    candidates: list[tuple[str, str, float]] = []
    for line in lines:
        if _line_is_negative_routing_context(line):
            continue
        target = _target_from_snippet(line)
        if target:
            candidates.append((target, _department_for_target(target), 0.78))
            continue
        if any(marker in line.lower() for marker in ("grund", "anamnese", "fragestellung", "verlauf")):
            target = _target_from_snippet(line, include_keywords=True)
            if target:
                candidates.append((target, _department_for_target(target), 0.66))

    if not candidates:
        return None
    best_confidence = max(candidate[2] for candidate in candidates)
    best = [candidate for candidate in candidates if candidate[2] == best_confidence]
    return best[0] if len({candidate[0] for candidate in best}) == 1 else None


def _infer_routing(text: str, lines: list[str] | None = None) -> tuple[str, str, float] | None:
    lowered = text.lower()
    if any(
        marker in lowered
        for marker in (
            "mehrdeutig",
            "unklare zuordnung",
            "keine klare fachliche",
            "geeignete sprechstunde pruefen",
            "geeignete sprechstunde prüfen",
        )
    ):
        return None
    return _infer_routing_from_lines(lines or [_clean(line) for line in text.splitlines() if _clean(line)])


def _merge_routing(analysis: ReferralAnalysis, text: str, lines: list[str]) -> bool:
    explicit = _explicit_routing_from_lines(lines)
    if explicit:
        target, evidence_line = explicit
        changed = analysis.routing_proposal.routing_target != target
        analysis.routing_proposal.routing_target = target
        analysis.routing_proposal.department = _department_for_target(target)
        analysis.routing_proposal.confidence = 0.9
        if analysis.routing_proposal.administrative_urgency == "unknown":
            analysis.routing_proposal.administrative_urgency = "human_review"
        _add_evidence(analysis, "routing_proposal.routing_target", evidence_line)
        if changed:
            _add_warning(
                analysis,
                "Routing target was normalized from an explicit document routing field.",
            )
        return True

    if analysis.routing_proposal.routing_target and analysis.routing_proposal.confidence >= 0.6:
        return False
    inferred = _infer_routing(text, lines)
    if not inferred:
        return False
    target, department, confidence = inferred
    analysis.routing_proposal.routing_target = target
    analysis.routing_proposal.department = department
    analysis.routing_proposal.confidence = max(min(analysis.routing_proposal.confidence, confidence), confidence)
    if analysis.routing_proposal.administrative_urgency == "unknown":
        analysis.routing_proposal.administrative_urgency = "human_review"
    return True


def apply_text_extraction_fallback(analysis: ReferralAnalysis, document_text: str) -> ReferralAnalysis:
    lines = [_clean(line) for line in document_text.splitlines() if _clean(line)]
    changed = False
    changed = _merge_patient(analysis, lines) or changed
    changed = _merge_referring_party(analysis, lines) or changed
    changed = _merge_clinical_context(analysis, lines, document_text) or changed
    changed = _merge_attachments(analysis, document_text) or changed
    changed = _merge_routing(analysis, document_text, lines) or changed

    if changed:
        if analysis.routing_proposal.confidence < 0.9:
            analysis.routing_proposal.confidence = min(analysis.routing_proposal.confidence, 0.85)
        _add_warning(
            analysis,
            "Explicit administrative fields were filled from deterministic document text extraction.",
        )
    return analysis
