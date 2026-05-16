from __future__ import annotations

from backend.app.core.config import Settings

ALLOWED_DESTRUCTIVE_EVAL_DATABASES = {
    "sqlite:///./test_hospital_ai.db",
    "sqlite:///./eval_hospital_ai.db",
    "sqlite:///./eval_referral_batch.db",
    "sqlite:///./prototype_eval_referrals.db",
    "sqlite:///./prototype_eval_guidelines.db",
    "sqlite:///:memory:",
}


def assert_destructive_eval_allowed(settings: Settings) -> None:
    if settings.app_env != "demo":
        raise RuntimeError("Refusing destructive evaluation outside APP_ENV=demo")

    if settings.database_url not in ALLOWED_DESTRUCTIVE_EVAL_DATABASES:
        raise RuntimeError(
            "Refusing destructive evaluation for this DATABASE_URL. "
            "Use a dedicated synthetic eval SQLite database."
        )
