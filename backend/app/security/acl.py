from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.core.errors import forbidden, not_found
from backend.app.db.models import Document, ReferralCase
from backend.app.security.auth import DemoUser
from backend.app.security.groups import GROUP_ADMIN, GROUP_IT_USERS, GROUP_REFERRAL_REVIEWERS


def is_admin(user: DemoUser) -> bool:
    return GROUP_ADMIN in user.groups or user.role == GROUP_ADMIN


def has_group_overlap(user: DemoUser, access_groups: list[str] | None) -> bool:
    if not access_groups:
        return False
    return bool(set(user.groups).intersection(access_groups))


def require_visible(user: DemoUser, access_groups: list[str] | None) -> None:
    if not access_groups:
        raise forbidden("User is not allowed to access this document")
    if is_admin(user):
        return
    if not has_group_overlap(user, access_groups):
        raise forbidden("User is not allowed to access this document")


def require_admin(user: DemoUser) -> None:
    if not is_admin(user):
        raise forbidden("Admin access required")


def require_admin_or_it(user: DemoUser) -> None:
    if not is_admin(user) and GROUP_IT_USERS not in user.groups:
        raise forbidden("Admin or IT access required")


def require_any_group(user: DemoUser, groups: list[str], detail: str = "Access denied") -> None:
    if not set(user.groups).intersection(groups):
        raise forbidden(detail)


def require_referral_reviewer(user: DemoUser) -> None:
    if is_admin(user):
        return
    require_any_group(user, [GROUP_REFERRAL_REVIEWERS], "Referral workflow requires reviewer access")


def require_guideline_ingest_permission(user: DemoUser) -> None:
    if not is_admin(user) and GROUP_IT_USERS not in user.groups:
        raise forbidden("Guideline ingestion requires admin or IT access")


def require_referral_case_visible(session: Session, case_id: str, user: DemoUser) -> ReferralCase:
    case = session.get(ReferralCase, case_id)
    if not case:
        raise not_found("Referral case not found")

    document = session.get(Document, case.document_id)
    if not document:
        raise not_found("Linked document not found")

    require_visible(user, document.access_groups)
    return case
