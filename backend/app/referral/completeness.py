from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml
from pydantic import BaseModel

from backend.app.core.config import get_settings
from backend.app.referral.schemas import MissingItem, ReferralAnalysis


@lru_cache
def load_completeness_rules() -> dict:
    path = get_settings().project_root / "configs" / "completeness_rules.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _get_path(value: Any, dotted: str) -> Any:
    current = value
    for part in dotted.split("."):
        if isinstance(current, BaseModel):
            current = getattr(current, part, None)
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or value == []


def check_completeness(analysis: ReferralAnalysis) -> list[MissingItem]:
    rules = load_completeness_rules()
    target = analysis.routing_proposal.routing_target or "global"
    department_rules = rules.get("rules_by_department", {}).get(target, {})
    required = list(rules.get("global_required", [])) + list(department_rules.get("required", []))
    blocking = set(department_rules.get("blocking_if_missing", []))
    recommended_attachments = department_rules.get("recommended_attachments", [])

    missing: list[MissingItem] = []
    seen: set[str] = set()
    for field in required:
        if field in seen:
            continue
        seen.add(field)
        if _is_missing(_get_path(analysis, field)):
            missing.append(
                MissingItem(
                    field=field,
                    reason="Pflichtangabe fehlt oder ist unklar.",
                    severity="blocking" if field in blocking else "recommended",
                )
            )

    for attachment in recommended_attachments:
        status = getattr(analysis.attachments, attachment, "unclear")
        if status in {"missing", "unclear"}:
            missing.append(
                MissingItem(
                    field=f"attachments.{attachment}",
                    reason="Empfohlene Beilage fehlt oder ist unklar.",
                    severity="recommended",
                )
            )
    return missing

