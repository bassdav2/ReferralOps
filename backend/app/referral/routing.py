from __future__ import annotations

import re
from functools import lru_cache

import yaml

from backend.app.core.config import get_settings
from backend.app.referral.schemas import ReferralAnalysis


@lru_cache
def load_routing_taxonomy() -> dict:
    path = get_settings().project_root / "configs" / "routing_taxonomy.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def allowed_targets() -> list[str]:
    return list(load_routing_taxonomy()["routing_targets"].keys())


def _slug(value: str) -> str:
    normalized = value.strip().lower()
    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
    }
    for raw, replacement in replacements.items():
        normalized = normalized.replace(raw, replacement)
    normalized = normalized.replace("&", " und ")
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return re.sub(r"_+", "_", normalized).strip("_")


def routing_target_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for target, metadata in load_routing_taxonomy()["routing_targets"].items():
        values = {target, _slug(target)}
        for field in ("display_name", "department"):
            value = metadata.get(field)
            if value:
                values.add(str(value))
                values.add(_slug(str(value)))
        for alias in metadata.get("aliases", []):
            values.add(str(alias))
            values.add(_slug(str(alias)))
        for value in values:
            aliases[str(value).strip().lower()] = target
            aliases[_slug(str(value))] = target
    return aliases


def canonical_routing_target(target: str | None) -> str | None:
    if target is None:
        return None
    stripped = target.strip()
    if not stripped:
        return None
    aliases = routing_target_aliases()
    return aliases.get(stripped.lower()) or aliases.get(_slug(stripped))


def _department_name(metadata: dict) -> str | None:
    return metadata.get("display_name") or metadata.get("department")


def _map_secondary_suggestions(analysis: ReferralAnalysis) -> None:
    taxonomy = load_routing_taxonomy()["routing_targets"]
    for suggestion in analysis.secondary_routing_targets:
        raw = suggestion.routing_target or suggestion.label or suggestion.department
        mapped = canonical_routing_target(raw)
        if mapped:
            suggestion.routing_target = mapped
            suggestion.department = _department_name(taxonomy[mapped])


def enforce_allowed_routing(analysis: ReferralAnalysis) -> ReferralAnalysis:
    taxonomy = load_routing_taxonomy()["routing_targets"]
    raw_target = analysis.routing_proposal.routing_target
    target = canonical_routing_target(raw_target)

    if not target and analysis.model_suggested_destination and analysis.model_suggested_destination.label:
        target = canonical_routing_target(analysis.model_suggested_destination.label)
        if target and not raw_target:
            analysis.routing_proposal.routing_target = target

    if analysis.model_suggested_destination:
        analysis.model_suggested_destination.mapped_to_routing_target = target

    if raw_target and not target:
        analysis.routing_proposal.routing_target = None
        analysis.routing_proposal.department = None
        analysis.routing_proposal.confidence = min(analysis.routing_proposal.confidence, 0.3)
        analysis.human_review_required = True
        warning = f"Routing target '{raw_target}' is not in taxonomy."
        if warning not in analysis.warnings:
            analysis.warnings.append(warning)
    elif target:
        analysis.routing_proposal.routing_target = target
        analysis.routing_proposal.department = _department_name(taxonomy[target])

    _map_secondary_suggestions(analysis)

    if not analysis.routing_proposal.routing_target:
        analysis.routing_proposal.department = None
        analysis.routing_proposal.confidence = min(analysis.routing_proposal.confidence, 0.3)
        analysis.human_review_required = True
    return analysis
