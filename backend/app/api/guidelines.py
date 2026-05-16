from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.errors import bad_request
from backend.app.db.session import get_session
from backend.app.model_gateway import get_embedding_client
from backend.app.rag.answerer import answer_guideline_question, persist_feedback
from backend.app.rag.ingest import ingest_guideline_sources
from backend.app.rag.retriever import search_chunks
from backend.app.rag.schemas import GuidelineAnswer, GuidelineChatRequest, GuidelineFeedbackRequest, RetrievedChunk
from backend.app.security.acl import require_guideline_ingest_permission
from backend.app.security.auth import DemoUser, get_current_user

router = APIRouter(prefix="/api/guidelines", tags=["guidelines"])


@router.post("/ingest")
def ingest(session: Session = Depends(get_session), user: DemoUser = Depends(get_current_user)) -> dict:
    require_guideline_ingest_permission(user)
    return ingest_guideline_sources(session)


@router.post("/search", response_model=list[RetrievedChunk])
def search(
    request: GuidelineChatRequest,
    session: Session = Depends(get_session),
    user: DemoUser = Depends(get_current_user),
) -> list[RetrievedChunk]:
    settings = get_settings()
    if len(request.question) > settings.max_guideline_question_chars:
        raise bad_request("Question too long for demo")
    embedding = get_embedding_client().embed_query(request.question)
    return search_chunks(session, query=request.question, query_vector=embedding, user=user, top_k=5)


@router.post("/chat", response_model=GuidelineAnswer)
def chat(
    request: GuidelineChatRequest,
    session: Session = Depends(get_session),
    user: DemoUser = Depends(get_current_user),
) -> GuidelineAnswer:
    return answer_guideline_question(session, request.question, user)


@router.post("/feedback")
def feedback(
    request: GuidelineFeedbackRequest,
    session: Session = Depends(get_session),
    user: DemoUser = Depends(get_current_user),
) -> dict:
    return persist_feedback(session, request, user)
