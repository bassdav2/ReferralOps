from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api import admin, documents, guidelines, health, referrals, runtime
from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging
from backend.app.db.session import SessionLocal, init_db
from backend.app.referral.demo_preload import preload_referral_demo_state
from backend.app.security.auth import seed_demo_users


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as session:
        seed_demo_users(session)
        preload_referral_demo_state(session)
    yield


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        title="Hospital AI Assistant",
        description="Local administrative AI assistant demo for referral preparation and guideline RAG.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(documents.router)
    app.include_router(referrals.router)
    app.include_router(guidelines.router)
    app.include_router(admin.router)
    app.include_router(runtime.router)

    return app


app = create_app()
