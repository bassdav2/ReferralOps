#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
DEMO_USER="${DEMO_USER:-sekretariat_kardiologie}"
PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"

if curl -fsS --max-time 2 "$BACKEND_URL/api/health" >/dev/null 2>&1; then
  echo "Backend is running; resetting the demo through the API."
  curl -fsS \
    -X POST "$BACKEND_URL/api/referrals/demo-reset" \
    -H "X-Demo-User: $DEMO_USER" \
    >/dev/null
  echo "Demo reset complete."
  exit 0
fi

if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port 8000 is in use, but the backend health check failed."
  echo "Refusing to delete SQLite files while a server may still hold an open database handle."
  echo "Stop or restart the backend, then run reset again."
  exit 1
fi

rm -f hospital_ai.db test_hospital_ai.db data/*.db
rm -rf data/uploads/*
rm -rf data/referral_inbox/*
find demo_outputs -name '*.json' -delete 2>/dev/null || true
mkdir -p data/uploads data/referral_inbox
touch data/uploads/.gitkeep
touch data/referral_inbox/.gitkeep

"$PYTHON_BIN" - <<'PY'
from backend.app.db.session import SessionLocal, init_db
from backend.app.security.auth import seed_demo_users

init_db()
with SessionLocal() as session:
    seed_demo_users(session)
PY

echo "Demo reset complete."
