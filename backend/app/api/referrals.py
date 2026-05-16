from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.errors import bad_request
from backend.app.db.session import get_session
from backend.app.referral.batch_summary import compute_referral_batch_summary
from backend.app.referral.demo_outputs import list_demo_outputs
from backend.app.referral.demo_reset import reset_referral_demo_state
from backend.app.referral.inbox_processing import (
    InboxUploadFile,
    get_referral_inbox_summary,
    process_referral_inbox,
    upload_referral_inbox_files,
)
from backend.app.referral.pipeline_events import list_pipeline_events
from backend.app.referral.review import review_referral_case
from backend.app.referral.routing import load_routing_taxonomy
from backend.app.referral.schemas import (
    ReferralBatchSummary,
    ReferralCaseRead,
    ReferralDemoOutputRead,
    ReferralDemoResetResult,
    ReferralInboxProcessRequest,
    ReferralInboxProcessResult,
    ReferralInboxSummary,
    ReferralInboxUploadResult,
    ReferralIngestReport,
    ReferralPipelineEventRead,
    ReferralRoutingTargetRead,
    ReferralWorklistFilter,
    ReferralWorklistItem,
    ReviewRead,
    ReviewRequest,
)
from backend.app.referral.service import analyze_referral, get_referral_case
from backend.app.referral.worklist import list_referral_worklist
from backend.app.referral.writeback import writeback_case
from backend.app.security.auth import DemoUser, get_current_user

router = APIRouter(prefix="/api/referrals", tags=["referrals"])


async def _read_inbox_upload(file: UploadFile, max_bytes: int) -> InboxUploadFile:
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > max_bytes:
            return InboxUploadFile(
                file_name=file.filename or "upload.pdf",
                content_type=file.content_type,
                content=b"",
                validation_error=f"File exceeds {max_bytes // (1024 * 1024)} MB upload limit.",
            )
        chunks.append(chunk)
    return InboxUploadFile(
        file_name=file.filename or "upload.pdf",
        content_type=file.content_type,
        content=b"".join(chunks),
    )


@router.post("/analyze/{document_id}", response_model=ReferralCaseRead)
def analyze(
    document_id: str,
    session: Session = Depends(get_session),
    user: DemoUser = Depends(get_current_user),
) -> ReferralCaseRead:
    return analyze_referral(session, document_id, user)


@router.get("/cases", response_model=list[ReferralWorklistItem])
def list_cases(
    filter: ReferralWorklistFilter = "all",
    session: Session = Depends(get_session),
    user: DemoUser = Depends(get_current_user),
) -> list[ReferralWorklistItem]:
    return list_referral_worklist(session, user, filter)


@router.get("/batch-summary", response_model=ReferralBatchSummary)
def batch_summary(
    session: Session = Depends(get_session),
    user: DemoUser = Depends(get_current_user),
) -> ReferralBatchSummary:
    return compute_referral_batch_summary(session, user)


@router.get("/pipeline-events", response_model=list[ReferralPipelineEventRead])
def pipeline_events(
    limit: int = Query(100, ge=1, le=500),
    document_id: str | None = None,
    case_id: str | None = None,
    session: Session = Depends(get_session),
    user: DemoUser = Depends(get_current_user),
) -> list[ReferralPipelineEventRead]:
    return list_pipeline_events(session, user, limit=limit, document_id=document_id, case_id=case_id)


@router.get("/demo-outputs", response_model=list[ReferralDemoOutputRead])
def demo_outputs(
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
    user: DemoUser = Depends(get_current_user),
) -> list[ReferralDemoOutputRead]:
    return list_demo_outputs(session, user, limit=limit)


@router.get("/inbox-summary", response_model=ReferralInboxSummary)
def inbox_summary(
    session: Session = Depends(get_session),
    user: DemoUser = Depends(get_current_user),
) -> ReferralInboxSummary:
    return get_referral_inbox_summary(session, user)


@router.post("/process-inbox", response_model=ReferralInboxProcessResult)
def process_inbox(
    request: ReferralInboxProcessRequest,
    session: Session = Depends(get_session),
    user: DemoUser = Depends(get_current_user),
) -> ReferralInboxProcessResult:
    return process_referral_inbox(session, user, limit=request.limit)


@router.post("/inbox/upload", response_model=ReferralInboxUploadResult)
async def upload_inbox(
    files: list[UploadFile] = File(...),
    session: Session = Depends(get_session),
    user: DemoUser = Depends(get_current_user),
) -> ReferralInboxUploadResult:
    settings = get_settings()
    if len(files) > settings.referral_inbox_max_files:
        raise bad_request(f"Too many files. Limit is {settings.referral_inbox_max_files} files per request.")
    uploads = [await _read_inbox_upload(file, settings.referral_inbox_max_upload_bytes) for file in files]
    return upload_referral_inbox_files(session, user, uploads)


@router.get("/routing-targets", response_model=list[ReferralRoutingTargetRead])
def routing_targets(
    user: DemoUser = Depends(get_current_user),
) -> list[ReferralRoutingTargetRead]:
    from backend.app.security.acl import require_referral_reviewer

    require_referral_reviewer(user)
    targets = load_routing_taxonomy()["routing_targets"]
    return [
        ReferralRoutingTargetRead(
            routing_target=routing_target,
            department=metadata.get("display_name") or metadata.get("department") or routing_target,
        )
        for routing_target, metadata in targets.items()
    ]


@router.post("/ingest-demo-sources", response_model=ReferralIngestReport)
def ingest_demo_referral_sources(
    session: Session = Depends(get_session),
    user: DemoUser = Depends(get_current_user),
) -> ReferralIngestReport:
    from backend.app.referral.ingest import ingest_referral_sources_report
    from backend.app.security.acl import require_admin

    require_admin(user)
    return ReferralIngestReport.model_validate(ingest_referral_sources_report(session, user))


@router.post("/demo-reset", response_model=ReferralDemoResetResult)
def reset_demo(
    session: Session = Depends(get_session),
    user: DemoUser = Depends(get_current_user),
) -> ReferralDemoResetResult:
    from backend.app.security.acl import require_admin

    require_admin(user)
    return reset_referral_demo_state(session, user)


@router.get("/{case_id}", response_model=ReferralCaseRead)
def get_case(
    case_id: str,
    session: Session = Depends(get_session),
    user: DemoUser = Depends(get_current_user),
) -> ReferralCaseRead:
    return get_referral_case(session, case_id, user)


@router.post("/{case_id}/review", response_model=ReviewRead)
def review_case(
    case_id: str,
    request: ReviewRequest,
    session: Session = Depends(get_session),
    user: DemoUser = Depends(get_current_user),
) -> ReviewRead:
    return review_referral_case(session, case_id, user, request)


@router.post("/{case_id}/writeback")
def writeback(
    case_id: str,
    session: Session = Depends(get_session),
    user: DemoUser = Depends(get_current_user),
) -> dict:
    return writeback_case(session, case_id, user)
