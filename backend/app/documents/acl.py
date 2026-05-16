from __future__ import annotations

from backend.app.security.groups import GROUP_ALL_STAFF


def validate_document_acl(*, access_groups: list[str] | None, contains_patient_data: bool) -> list[str]:
    groups = list(access_groups) if access_groups is not None else []
    if contains_patient_data:
        if not groups:
            raise ValueError("Patient documents require explicit access groups")
        if GROUP_ALL_STAFF in groups:
            raise ValueError("Patient documents may not use all_staff ACL in demo")
    return groups
