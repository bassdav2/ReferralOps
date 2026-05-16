from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
os.environ["HOSPITAL_AI_ROOT"] = str(ROOT)
os.environ["DATABASE_URL"] = "sqlite:///./test_hospital_ai.db"
os.environ["MODEL_PROVIDER"] = "test_double"
os.environ["EMBEDDING_PROVIDER"] = "test_double"
os.environ["NO_EXTERNAL_AI_CALLS"] = "true"
os.environ["DEMO_PRELOAD_REFERRALS"] = "false"
os.environ["GUIDELINE_EXTRACTIVE_MODE"] = "false"

from backend.app.core.config import get_settings
from backend.app.db.models import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.referral.completeness import load_completeness_rules
from backend.app.referral.routing import load_routing_taxonomy
from backend.app.security.auth import load_demo_users, seed_demo_users


def clear_runtime_caches() -> None:
    get_settings.cache_clear()
    load_demo_users.cache_clear()
    load_routing_taxonomy.cache_clear()
    load_completeness_rules.cache_clear()


def write_minimal_referral_runtime_configs(root: Path) -> None:
    configs = root / "configs"
    configs.mkdir(exist_ok=True)

    (configs / "demo_users.yml").write_text(
        """
users:
  sekretariat_kardiologie:
    role: staff
    groups: [referral_reviewers, kardiologie]
  it_admin:
    role: admin
    groups: [admin, it_users, all_staff]
  hygiene_user:
    role: staff
    groups: [hygiene, all_staff]
  restricted_user:
    role: staff
    groups: [all_staff]
""",
        encoding="utf-8",
    )
    (configs / "routing_taxonomy.yml").write_text(
        """
routing_targets:
  kardiologie:
    department: Kardiologie
  radiologie:
    department: Radiologie
  gynaekologie:
    department: Gynaekologie
  allgemeinambulanz:
    department: Allgemeinambulanz
  notfallnahe_abklaerung:
    department: Notfallnahe Abklärung
    aliases:
      - notfallnahe abklärung
      - notfallnahe abklaerung
  pflegekoordination:
    department: Pflegekoordination
""",
        encoding="utf-8",
    )
    (configs / "completeness_rules.yml").write_text(
        """
global_required: []
rules_by_department:
  kardiologie:
    required: []
    blocking_if_missing: []
    recommended_attachments:
      - medication_list
  radiologie:
    required: []
    blocking_if_missing: []
    recommended_attachments: []
  gynaekologie:
    required: []
    blocking_if_missing: []
    recommended_attachments: []
  global:
    required: []
    blocking_if_missing: []
    recommended_attachments: []
""",
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def clean_db(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("REFERRAL_DEMO_OUTPUT_DIR", str(tmp_path / "demo_outputs" / "referrals"))
    monkeypatch.setenv("DEMO_OUTPUTS_ENABLED", "true")
    monkeypatch.setenv("LOCAL_MODEL_CONFIG_PATH", str(tmp_path / "data" / "local_model_config.json"))
    clear_runtime_caches()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        seed_demo_users(session)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def isolated_project_root(tmp_path: Path, monkeypatch):
    root = tmp_path
    (root / "data" / "uploads").mkdir(parents=True)
    write_minimal_referral_runtime_configs(root)
    monkeypatch.setenv("HOSPITAL_AI_ROOT", str(root))
    clear_runtime_caches()
    return root


@pytest.fixture
def reset_runtime_caches():
    return clear_runtime_caches


@pytest.fixture
def session():
    with SessionLocal() as db:
        yield db
