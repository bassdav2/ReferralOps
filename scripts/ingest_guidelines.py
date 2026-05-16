from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.db.session import SessionLocal, init_db
from backend.app.rag.ingest import ingest_guideline_sources
from backend.app.security.auth import seed_demo_users


def main() -> None:
    init_db()
    with SessionLocal() as session:
        seed_demo_users(session)
        result = ingest_guideline_sources(session)
    print(result)


if __name__ == "__main__":
    main()
