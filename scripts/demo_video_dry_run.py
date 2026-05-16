from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.core.config import get_settings
from backend.app.db.models import Base, ReferralCase, ReferralPipelineEvent
from backend.app.db.session import SessionLocal, engine
from backend.app.referral.batch_summary import compute_referral_batch_summary
from backend.app.referral.demo_outputs import list_demo_outputs
from backend.app.referral.ingest import ingest_referral_sources_report, load_referral_source_config
from backend.app.referral.review import review_referral_case
from backend.app.referral.routing import load_routing_taxonomy
from backend.app.referral.schemas import ReferralAnalysis, ReviewRequest
from backend.app.referral.service import analyze_referral
from backend.app.referral.worklist import list_referral_worklist
from backend.app.security.auth import get_current_user, seed_demo_users


def ensure_demo_inbox_samples() -> None:
    settings = get_settings()
    source_dir = settings.project_root / "demos" / "referral_inbox_samples"
    if not source_dir.exists():
        source_dir = ROOT / "demos" / "referral_inbox_samples"
    if not source_dir.exists():
        raise RuntimeError("Missing demos/referral_inbox_samples")
    config = load_referral_source_config()
    inbox_dirs: list[Path] = []
    for source in config.get("sources", {}).values():
        if source.get("adapter") != "filesystem":
            continue
        raw_path = Path(source.get("path") or settings.referral_inbox_dir)
        inbox_dirs.append(raw_path if raw_path.is_absolute() else settings.project_root / raw_path)
    if not inbox_dirs:
        inbox_dirs.append(settings.referral_inbox_dir)
    for inbox_dir in inbox_dirs:
        inbox_dir.mkdir(parents=True, exist_ok=True)
        for source in sorted(source_dir.glob("*.pdf")):
            target = inbox_dir / source.name
            if not target.exists():
                shutil.copy2(source, target)


def _latest_cases(session) -> list[ReferralCase]:
    cases = (
        session.query(ReferralCase)
        .order_by(ReferralCase.created_at.desc(), ReferralCase.id.desc())
        .all()
    )
    latest_by_document: dict[str, ReferralCase] = {}
    for case in cases:
        latest_by_document.setdefault(case.document_id, case)
    return sorted(latest_by_document.values(), key=lambda case: (case.created_at, case.id))


def _analyze_subset(session, *, limit: int) -> None:
    user = get_current_user("sekretariat_kardiologie")
    items = list_referral_worklist(session, user, "all")
    analyzed_document_ids = {item.document_id for item in items if item.case_id}
    analyzed = 0
    for item in sorted(items, key=lambda row: row.document_title):
        if analyzed >= limit:
            break
        if item.document_id in analyzed_document_ids:
            continue
        analyze_referral(session, item.document_id, user)
        analyzed += 1


def _corrected_analysis(case: ReferralCase) -> ReferralAnalysis:
    analysis = ReferralAnalysis.model_validate(case.analysis_json)
    taxonomy = load_routing_taxonomy()["routing_targets"]
    target = analysis.routing_proposal.routing_target or next(iter(taxonomy))
    metadata = taxonomy[target]
    analysis.patient.phone = analysis.patient.phone or "+41 44 999 00 00"
    analysis.patient.insurance_id = analysis.patient.insurance_id or "SYN-DRY-RUN"
    analysis.routing_proposal.routing_target = target
    analysis.routing_proposal.department = metadata.get("display_name") or metadata.get("department") or target
    return analysis


def _perform_demo_reviews(session, *, limit: int) -> None:
    user = get_current_user("sekretariat_kardiologie")
    decisions = ["confirm", "correct", "question", "reject"]
    cases = [case for case in _latest_cases(session) if case.reviewed_at is None]
    if len(cases) < min(len(decisions), limit):
        for item in list_referral_worklist(session, user, "all")[:limit]:
            analyze_referral(session, item.document_id, user)
        cases = [case for case in _latest_cases(session) if case.reviewed_at is None]

    for decision, case in zip(decisions, cases, strict=False):
        corrected = _corrected_analysis(case) if decision == "correct" else None
        review_referral_case(
            session,
            case.id,
            user,
            ReviewRequest(
                decision=decision,
                corrected_analysis=corrected,
                comment=f"Demo dry-run decision: {decision}",
            ),
        )


def run_demo_video_dry_run(*, limit: int = 10) -> dict:
    ensure_demo_inbox_samples()
    Base.metadata.create_all(bind=engine)
    user = get_current_user("sekretariat_kardiologie")
    with SessionLocal() as session:
        seed_demo_users(session)
        ingest_report = ingest_referral_sources_report(session, user)
        _analyze_subset(session, limit=limit)
        _perform_demo_reviews(session, limit=limit)
        events_count = session.query(ReferralPipelineEvent).count()
        worklist_items = list_referral_worklist(session, user, "all")
        summary = compute_referral_batch_summary(session, user)
        outputs = list_demo_outputs(session, user, limit=200)

    result = {
        "ingest": ingest_report,
        "pipeline_events": events_count,
        "worklist_items": len(worklist_items),
        "review_required": summary.review_required,
        "summary": summary.model_dump(mode="json"),
        "outputs_written": len(outputs),
        "output_paths": [output.relative_path for output in outputs],
    }
    if result["pipeline_events"] <= 0:
        raise RuntimeError("Dry run failed: no pipeline events were written")
    if result["outputs_written"] <= 0:
        raise RuntimeError("Dry run failed: no output JSON was written")
    if result["worklist_items"] <= 0:
        raise RuntimeError("Dry run failed: no worklist items exist")
    if summary.total_documents <= 0:
        raise RuntimeError("Dry run failed: batch summary is empty")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the referral hackathon demo flow against the configured local or test model path."
    )
    parser.add_argument("--limit", type=int, default=10, help="Maximum referral documents to analyze in the dry run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = run_demo_video_dry_run(limit=args.limit)
    except Exception as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1) from exc

    print(f"pipeline events: {result['pipeline_events']}")
    print(f"worklist items: {result['worklist_items']}")
    print(f"review required: {result['review_required']}")
    print(f"outputs written: {result['outputs_written']}")
    print("batch summary:")
    print(f"  total_documents: {result['summary']['total_documents']}")
    print(f"  analyzed: {result['summary']['analyzed']}")
    print(f"  confirmed: {result['summary']['confirmed']}")
    print(f"  corrected: {result['summary']['corrected']}")
    print(f"  questions: {result['summary']['questions']}")
    print(f"  rejected: {result['summary']['rejected']}")
    print("output paths:")
    for path in result["output_paths"]:
        print(f"  - {path}")


if __name__ == "__main__":
    main()
