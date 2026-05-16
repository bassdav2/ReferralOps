from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import Settings, get_settings
from backend.app.db.models import Base


def _engine_kwargs(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {}


def create_engine_from_settings(settings: Settings) -> Engine:
    return create_engine(settings.database_url, **_engine_kwargs(settings.database_url))


def create_sessionmaker(db_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=db_engine, autoflush=False, autocommit=False, expire_on_commit=False)


settings = get_settings()
engine = create_engine_from_settings(settings)
SessionLocal = create_sessionmaker(engine)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def ping_db() -> bool:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return True


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
