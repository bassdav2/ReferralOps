from __future__ import annotations

from dataclasses import replace

import pytest

from backend.app.core.config import get_settings
from backend.app.evaluation.safety import assert_destructive_eval_allowed


def test_destructive_eval_allows_demo_eval_sqlite():
    settings = replace(get_settings(), app_env="demo", database_url="sqlite:///./eval_hospital_ai.db")

    assert_destructive_eval_allowed(settings)


def test_destructive_eval_allows_prototype_acceptance_eval_databases():
    for database_url in [
        "sqlite:///./prototype_eval_referrals.db",
        "sqlite:///./prototype_eval_guidelines.db",
        "sqlite:///./eval_referral_batch.db",
    ]:
        settings = replace(get_settings(), app_env="demo", database_url=database_url)
        assert_destructive_eval_allowed(settings)


def test_destructive_eval_rejects_normal_demo_database():
    settings = replace(get_settings(), app_env="demo", database_url="sqlite:///./hospital_ai.db")

    with pytest.raises(RuntimeError):
        assert_destructive_eval_allowed(settings)


def test_destructive_eval_rejects_prod_environment():
    settings = replace(get_settings(), app_env="prod", database_url="sqlite:///./eval_hospital_ai.db")

    with pytest.raises(RuntimeError):
        assert_destructive_eval_allowed(settings)


def test_destructive_eval_rejects_postgres_even_in_demo():
    settings = replace(
        get_settings(),
        app_env="demo",
        database_url="postgresql+psycopg://hospital_ai:hospital_ai@postgres:5432/hospital_ai",
    )

    with pytest.raises(RuntimeError):
        assert_destructive_eval_allowed(settings)
