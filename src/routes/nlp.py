from fastapi import APIRouter, Depends, Query, Request
from langdetect import DetectorFactory, LangDetectException, detect
from typing import List, Optional
import re

from helpers.config import Settings, get_settings
from models.ChatHistoryModel import MAX_CONVERSATION_MESSAGES
from models.db_schemes import User
from routes.dependencies import get_current_user
from routes.nlp_answer_orchestrator import handle_answer_rag
from routes.nlp_conversation_orchestrator import (
    handle_delete_conversation,
    handle_get_conversation_history,
    handle_list_conversations,
    handle_list_user_doc_types,
    handle_rename_conversation,
)
from routes.nlp_index_orchestrator import (
    handle_get_project_index_info,
    handle_index_project,
    handle_search_index,
)
from routes.nlp_summary_orchestrator import (
    handle_delete_summaries_bulk,
    handle_delete_summary,
    handle_get_summary,
    handle_list_summaries,
    handle_summarize_project,
)
from routes.schemes.nlp import (
    ConversationUpdateRequest,
    DeleteSummariesRequest,
    PushRequest,
    SearchRequest,
    SummarizeRequest,
)

DetectorFactory.seed = 0


nlp_router = APIRouter(
    prefix="/api/v1/nlp",
    tags=["api_v1", "nlp"],
)

KNOWN_DOCUMENT_TYPES = {"general", "military", "law", "finance"}
FILTERABLE_DOCUMENT_TYPES = KNOWN_DOCUMENT_TYPES - {"general"}


def detect_language_or_default(text: str, default: str) -> str:
    if not text:
        return default

    if re.search(r"[\u0600-\u06FF]", text):
        return "ar"

    if re.search(r"[A-Za-z]", text):
        return "en"

    try:
        lang = detect(text)
    except LangDetectException:
        return default

    if lang.startswith("ar"):
        return "ar"
    return "en"


def extract_document_types_from_query(query: str) -> List[str]:
    if not query:
        return []

    lowered = query.lower()
    matches = set()

    for doc_type in FILTERABLE_DOCUMENT_TYPES:
        trigger_phrases = [
            f"{doc_type} doc",
            f"{doc_type} docs",
            f"{doc_type} document",
            f"{doc_type} documents",
            f"from {doc_type}",
            f"in {doc_type} doc",
            f"in {doc_type} documents",
        ]

        if any(phrase in lowered for phrase in trigger_phrases):
            matches.add(doc_type)

    return list(matches)


@nlp_router.post("/index/push/{project_id}")
async def index_project(
    request: Request,
    project_id: int,
    push_request: PushRequest,
    current_user: User = Depends(get_current_user),
):
    return await handle_index_project(
        request=request,
        project_id=project_id,
        push_request=push_request,
        current_user=current_user,
    )


@nlp_router.get("/index/info/{project_id}")
async def get_project_index_info(
    request: Request,
    project_id: int,
    current_user: User = Depends(get_current_user),
):
    return await handle_get_project_index_info(
        request=request,
        project_id=project_id,
        current_user=current_user,
    )


@nlp_router.get("/conversations")
async def list_conversations(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return await handle_list_conversations(request=request, current_user=current_user)


@nlp_router.get("/doc-types")
async def list_user_doc_types(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return await handle_list_user_doc_types(request=request, current_user=current_user)


@nlp_router.get("/conversations/{conversation_id}/history")
async def get_conversation_history(
    request: Request,
    conversation_id: int,
    limit: Optional[int] = Query(None, ge=1, le=MAX_CONVERSATION_MESSAGES),
    current_user: User = Depends(get_current_user),
):
    return await handle_get_conversation_history(
        request=request,
        conversation_id=conversation_id,
        limit=limit,
        current_user=current_user,
    )


@nlp_router.patch("/conversations/{conversation_id}")
async def rename_conversation(
    request: Request,
    conversation_id: int,
    update: ConversationUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    return await handle_rename_conversation(
        request=request,
        conversation_id=conversation_id,
        update=update,
        current_user=current_user,
    )


@nlp_router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    request: Request,
    conversation_id: int,
    current_user: User = Depends(get_current_user),
):
    return await handle_delete_conversation(
        request=request,
        conversation_id=conversation_id,
        current_user=current_user,
    )


@nlp_router.post("/index/search/{project_id}")
async def search_index(
    request: Request,
    project_id: int,
    search_request: SearchRequest,
    current_user: User = Depends(get_current_user),
):
    return await handle_search_index(
        request=request,
        project_id=project_id,
        search_request=search_request,
        current_user=current_user,
    )


@nlp_router.post("/index/answer/{project_id}")
async def answer_rag(
    request: Request,
    project_id: int,
    search_request: SearchRequest,
    current_user: User = Depends(get_current_user),
    app_settings: Settings = Depends(get_settings),
):
    return await handle_answer_rag(
        request=request,
        project_id=project_id,
        search_request=search_request,
        current_user=current_user,
        app_settings=app_settings,
        language_detector=detect_language_or_default,
    )


@nlp_router.post("/summary/{project_id}")
async def summarize_project(
    request: Request,
    project_id: int,
    summarize_request: SummarizeRequest,
    current_user: User = Depends(get_current_user),
    app_settings: Settings = Depends(get_settings),
):
    return await handle_summarize_project(
        request=request,
        project_id=project_id,
        summarize_request=summarize_request,
        current_user=current_user,
        app_settings=app_settings,
        language_detector=detect_language_or_default,
    )


@nlp_router.get("/summary")
async def list_summaries(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
):
    return await handle_list_summaries(
        request=request,
        limit=limit,
        current_user=current_user,
    )


@nlp_router.get("/summary/{summary_id}")
async def get_summary(
    request: Request,
    summary_id: int,
    current_user: User = Depends(get_current_user),
    app_settings: Settings = Depends(get_settings),
):
    return await handle_get_summary(
        request=request,
        summary_id=summary_id,
        current_user=current_user,
        app_settings=app_settings,
    )


@nlp_router.delete("/summary/{summary_id}")
async def delete_summary(
    request: Request,
    summary_id: int,
    current_user: User = Depends(get_current_user),
):
    return await handle_delete_summary(
        request=request,
        summary_id=summary_id,
        current_user=current_user,
    )


@nlp_router.post("/summaries/bulk-delete")
async def delete_summaries_bulk(
    request: Request,
    payload: DeleteSummariesRequest,
    current_user: User = Depends(get_current_user),
):
    return await handle_delete_summaries_bulk(
        request=request,
        payload=payload,
        current_user=current_user,
    )
