from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    redis_url: str
    object_store_endpoint: str
    object_store_bucket: str
    object_store_access_key: str
    object_store_secret_key: str
    object_store_region: str
    object_store_timeout_seconds: float
    auth_mode: str
    model_provider: str
    local_llm_base_url: str
    local_llm_api_key: str | None
    local_llm_timeout_seconds: float
    local_llm_allowed_hosts: list[str]
    generation_model_id: str
    generation_max_tokens: int
    embedding_provider: str
    embedding_model_id: str
    local_embedding_model_path: str | None
    embedding_local_files_only: bool
    no_external_ai_calls: bool
    audit_log_enabled: bool
    store_prompt_text: bool
    store_model_output_text: bool
    writeback_enabled: bool
    demo_outputs_enabled: bool
    referral_demo_output_dir: Path
    demo_preload_referrals_enabled: bool
    demo_preload_referrals_dir: Path
    referral_inbox_backend: str
    referral_inbox_dir: Path
    referral_inbox_max_upload_bytes: int
    referral_inbox_max_files: int
    document_upload_max_bytes: int
    local_model_config_path: Path
    rag_top_k: int
    rag_context_top_n: int
    rag_min_relevance_score: float
    rag_lexical_weight: float
    rag_vector_weight: float
    guideline_extractive_mode: bool
    max_guideline_question_chars: int
    max_referral_text_chars: int
    ocr_enabled: bool
    ocr_languages: str
    ocr_dpi: int
    ocr_min_text_chars: int
    ocr_min_confidence: float
    ocr_max_pages: int
    ocr_max_pixels_per_page: int
    ocr_page_timeout_seconds: float
    ocr_total_timeout_seconds: float
    cors_origins: list[str]
    project_root: Path
    upload_dir: Path


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def _positive_float(name: str, default: float) -> float:
    value = _float(name, default)
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0")
    return value


def _non_negative_float(name: str, default: float) -> float:
    value = _float(name, default)
    if value < 0:
        raise ValueError(f"{name} must be 0 or greater")
    return value


def _positive_int(name: str, default: int) -> int:
    value = _int(name, default)
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0")
    return value


def _csv(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    root = Path(os.getenv("HOSPITAL_AI_ROOT", Path(__file__).resolve().parents[3]))
    try:
        from dotenv import load_dotenv

        load_dotenv(root / ".env", override=False)
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("Could not load .env file at %s: %s", root / ".env", exc)
    cors = os.getenv("BACKEND_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    upload_dir = root / "data" / "uploads"
    referral_inbox_dir = Path(os.getenv("REFERRAL_INBOX_DIR", str(root / "data" / "referral_inbox")))
    local_model_config_path = Path(os.getenv("LOCAL_MODEL_CONFIG_PATH", str(root / "data" / "local_model_config.json")))
    upload_dir.mkdir(parents=True, exist_ok=True)
    referral_inbox_dir.mkdir(parents=True, exist_ok=True)
    local_model_config_path.parent.mkdir(parents=True, exist_ok=True)
    return Settings(
        app_env=os.getenv("APP_ENV", "demo"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./hospital_ai.db"),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        object_store_endpoint=os.getenv("OBJECT_STORE_ENDPOINT", "http://localhost:9000"),
        object_store_bucket=os.getenv("OBJECT_STORE_BUCKET", "documents"),
        object_store_access_key=os.getenv("OBJECT_STORE_ACCESS_KEY", os.getenv("MINIO_ROOT_USER", "minio")),
        object_store_secret_key=os.getenv("OBJECT_STORE_SECRET_KEY", os.getenv("MINIO_ROOT_PASSWORD", "minio123")),
        object_store_region=os.getenv("OBJECT_STORE_REGION", "us-east-1"),
        object_store_timeout_seconds=_float("OBJECT_STORE_TIMEOUT_SECONDS", 3.0),
        auth_mode=os.getenv("AUTH_MODE", "demo"),
        model_provider=os.getenv("MODEL_PROVIDER", "gemma_vllm"),
        local_llm_base_url=os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:8080/v1"),
        local_llm_api_key=os.getenv("LOCAL_LLM_API_KEY") or None,
        local_llm_timeout_seconds=_non_negative_float("LOCAL_LLM_TIMEOUT_SECONDS", 0.0),
        local_llm_allowed_hosts=_csv(
            "LOCAL_LLM_ALLOWED_HOSTS",
            "localhost,127.0.0.1,model-server,host.docker.internal",
        ),
        generation_model_id=os.getenv("GENERATION_MODEL_ID", "google/gemma-4-31B-it"),
        generation_max_tokens=_int("GENERATION_MAX_TOKENS", 2048),
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "lexical_only"),
        embedding_model_id=os.getenv("EMBEDDING_MODEL_ID", "google/embeddinggemma-300m"),
        local_embedding_model_path=os.getenv("LOCAL_EMBEDDING_MODEL_PATH") or None,
        embedding_local_files_only=_bool("EMBEDDING_LOCAL_FILES_ONLY", True),
        no_external_ai_calls=_bool("NO_EXTERNAL_AI_CALLS", True),
        audit_log_enabled=_bool("AUDIT_LOG_ENABLED", True),
        store_prompt_text=_bool("STORE_PROMPT_TEXT", False),
        store_model_output_text=_bool("STORE_MODEL_OUTPUT_TEXT", False),
        writeback_enabled=_bool("WRITEBACK_ENABLED", False),
        demo_outputs_enabled=_bool("DEMO_OUTPUTS_ENABLED", True),
        referral_demo_output_dir=Path(
            os.getenv("REFERRAL_DEMO_OUTPUT_DIR", str(root / "demo_outputs" / "referrals"))
        ),
        demo_preload_referrals_enabled=_bool("DEMO_PRELOAD_REFERRALS", True),
        demo_preload_referrals_dir=Path(
            os.getenv("DEMO_PRELOAD_REFERRALS_DIR", str(root / "demos" / "referral_inbox_samples"))
        ),
        referral_inbox_backend=os.getenv("REFERRAL_INBOX_BACKEND", "filesystem").strip().lower(),
        referral_inbox_dir=referral_inbox_dir,
        referral_inbox_max_upload_bytes=_positive_int("REFERRAL_INBOX_MAX_UPLOAD_BYTES", 20 * 1024 * 1024),
        referral_inbox_max_files=_positive_int("REFERRAL_INBOX_MAX_FILES", 20),
        document_upload_max_bytes=_positive_int("DOCUMENT_UPLOAD_MAX_BYTES", 20 * 1024 * 1024),
        local_model_config_path=local_model_config_path,
        rag_top_k=_int("RAG_TOP_K", 20),
        rag_context_top_n=_int("RAG_CONTEXT_TOP_N", 3),
        rag_min_relevance_score=_float("RAG_MIN_RELEVANCE_SCORE", 0.18),
        rag_lexical_weight=_float("RAG_LEXICAL_WEIGHT", 0.75),
        rag_vector_weight=_float("RAG_VECTOR_WEIGHT", 0.25),
        guideline_extractive_mode=_bool("GUIDELINE_EXTRACTIVE_MODE", True),
        max_guideline_question_chars=_int("MAX_GUIDELINE_QUESTION_CHARS", 2000),
        max_referral_text_chars=_int("MAX_REFERRAL_TEXT_CHARS", 50000),
        ocr_enabled=_bool("OCR_ENABLED", True),
        ocr_languages=os.getenv("OCR_LANGUAGES", "deu+eng"),
        ocr_dpi=_int("OCR_DPI", 300),
        ocr_min_text_chars=_int("OCR_MIN_TEXT_CHARS", 24),
        ocr_min_confidence=_float("OCR_MIN_CONFIDENCE", 0.75),
        ocr_max_pages=_positive_int("OCR_MAX_PAGES", 20),
        ocr_max_pixels_per_page=_positive_int("OCR_MAX_PIXELS_PER_PAGE", 20_000_000),
        ocr_page_timeout_seconds=_positive_float("OCR_PAGE_TIMEOUT_SECONDS", 30.0),
        ocr_total_timeout_seconds=_positive_float("OCR_TOTAL_TIMEOUT_SECONDS", 180.0),
        cors_origins=[item.strip() for item in cors.split(",") if item.strip()],
        project_root=root,
        upload_dir=upload_dir,
    )
