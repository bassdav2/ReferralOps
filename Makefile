PYTHON ?= $(shell command -v python3.12 2>/dev/null || command -v python3)
VENV := .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python
UVICORN := $(VENV)/bin/uvicorn
REFERRAL_EVAL_ARGS ?=

.PHONY: check-runtime bootstrap demo-up demo-up-gpu demo-down minio-demo-up minio-demo-down compose-config compose-gpu-config backend-dev frontend-dev ingest-guidelines-demo demo-guidelines smoke-local-model local-model-smoke judge-smoke test test-e2e eval-referrals eval-guidelines hackathon-demo-dry-run lint ci reset-demo

check-runtime:
	$(PYTHON) scripts/check_runtime.py

bootstrap: check-runtime
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"
	npm --prefix frontend ci

demo-up:
	docker compose -f docker-compose.demo.yml up --build

demo-up-gpu:
	docker compose -f docker-compose.demo.yml -f docker-compose.gpu.yml up --build

demo-down:
	docker compose -f docker-compose.demo.yml down

minio-demo-up:
	docker compose -f docker-compose.demo.yml up -d minio minio-init
	@echo "MinIO console: http://localhost:9001"
	@echo "Login: minio / minio123"
	@echo "Referral bucket: referral-demo-inbox"

minio-demo-down:
	docker compose -f docker-compose.demo.yml stop minio minio-init

compose-config:
	docker compose -f docker-compose.demo.yml config

compose-gpu-config:
	docker compose -f docker-compose.demo.yml -f docker-compose.gpu.yml config

backend-dev:
	$(UVICORN) backend.app.main:app --host 0.0.0.0 --port 8000 --reload

frontend-dev:
	npm --prefix frontend run dev -- --host 0.0.0.0

ingest-guidelines-demo:
	$(PY) scripts/ingest_guidelines.py

demo-guidelines:
	$(PY) scripts/ingest_guidelines.py

smoke-local-model:
	RUN_REAL_LOCAL_MODEL_SMOKE=1 MODEL_PROVIDER=gemma_vllm $(PY) scripts/local_model_smoke.py

local-model-smoke:
	RUN_REAL_LOCAL_MODEL_SMOKE=1 MODEL_PROVIDER=gemma_vllm $(PY) scripts/local_model_smoke.py

judge-smoke:
	RUN_REAL_LOCAL_MODEL_SMOKE=1 MODEL_PROVIDER=gemma_vllm NO_EXTERNAL_AI_CALLS=true $(PY) scripts/local_model_smoke.py
	MODEL_PROVIDER=gemma_vllm NO_EXTERNAL_AI_CALLS=true DATABASE_URL=sqlite:///./eval_hospital_ai.db $(PY) scripts/evaluate_referral_batch.py --limit 10

test:
	$(PY) -m pytest

test-e2e:
	npm --prefix frontend run build

eval-referrals:
	$(PY) scripts/evaluate_referrals.py $(REFERRAL_EVAL_ARGS)

eval-guidelines:
	$(PY) scripts/evaluate_guidelines.py

hackathon-demo-dry-run:
	$(PY) scripts/demo_video_dry_run.py --limit 10

lint:
	$(PY) -m ruff check backend tests scripts demos
	$(PY) -m compileall backend scripts demos tests
	npm --prefix frontend run lint

ci:
	$(PY) -m pytest
	npm --prefix frontend ci
	npm --prefix frontend run build

reset-demo:
	bash scripts/reset_demo.sh
