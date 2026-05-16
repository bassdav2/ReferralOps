from __future__ import annotations

from functools import lru_cache
from typing import Annotated

import yaml
from fastapi import Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.errors import forbidden
from backend.app.db.models import User


class DemoUser(BaseModel):
    id: str
    username: str
    display_name: str
    role: str
    groups: list[str]


@lru_cache
def load_demo_users() -> dict[str, DemoUser]:
    path = get_settings().project_root / "configs" / "demo_users.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    users: dict[str, DemoUser] = {}
    for username, spec in data["users"].items():
        users[username] = DemoUser(
            id=username,
            username=username,
            display_name=username.replace("_", " ").title(),
            role=spec.get("role", "staff"),
            groups=spec.get("groups", []),
        )
    return users


def get_current_user(x_demo_user: Annotated[str | None, Header()] = None) -> DemoUser:
    settings = get_settings()
    if settings.auth_mode != "demo":
        raise forbidden("Only demo header auth is implemented in this prototype")
    users = load_demo_users()
    if not x_demo_user:
        raise forbidden("X-Demo-User header is required in demo auth mode")
    if x_demo_user not in users:
        raise forbidden("Unknown demo user")
    return users[x_demo_user]


def seed_demo_users(session: Session) -> None:
    for demo_user in load_demo_users().values():
        existing = session.get(User, demo_user.id)
        if existing:
            existing.groups = demo_user.groups
            existing.role = demo_user.role
            continue
        session.add(
            User(
                id=demo_user.id,
                username=demo_user.username,
                display_name=demo_user.display_name,
                role=demo_user.role,
                groups=demo_user.groups,
            )
        )
    session.commit()
