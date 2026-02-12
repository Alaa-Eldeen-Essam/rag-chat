from fastapi import APIRouter, status, Request, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from routes.schemes.nlp import PushRequest, SearchRequest, SummarizeRequest, ConversationUpdateRequest, DeleteSummariesRequest
from models.ProjectModel import ProjectModel
from models.ChunkModel import ChunkModel
from models.SummaryModel import SummaryModel
from controllers import NLPController
from models import ResponseSignal
from models.AssetModel import AssetModel
from models.ChatHistoryModel import ChatHistoryModel, MAX_CONVERSATION_MESSAGES
from models.ChatConversationModel import ChatConversationModel
from models.db_schemes import User, Asset, SummaryRecord
from routes.dependencies import get_current_user
from helpers.assets import get_asset_display_name
from helpers.config import get_settings, Settings
from stores.llm.templates.template_parser import TemplateParser
from langdetect import detect, LangDetectException, DetectorFactory
from models.enums.AssetTypeEnum import AssetTypeEnum
from sqlalchemy import select, or_
from types import SimpleNamespace
from tqdm.auto import tqdm

import logging
import json
import time
import math
from typing import List, Optional, Dict, Any
import re

from stores.llm.LLMEnums import DocumentTypeEnum
from routes.nlp_answer_orchestrator import handle_answer_rag
from routes.nlp_answer_utils import (
    build_answer_sources,
    clean_display_hint,
    compose_collector_output,
    default_answer_metadata,
    exposed_chat_history,
    exposed_full_prompt,
    looks_like_refusal,
    merged_answer_metadata,
    should_fallback_for_low_confidence,
)
from utils.grounding import grounding_report
from utils.prompt_guard import evaluate_prompt, should_bypass_prompt_guard
from utils.metrics import (
    PROMPT_GUARD_BYPASS_TOTAL,
    RAG_FALLBACK_TOTAL,
    RAG_CLARIFICATION_TOTAL,
    MULTIHOP_SCOPE_PROJECTS,
)

DetectorFactory.seed = 0

def detect_language_or_default(text: str, default: str) -> str:
    """
    Heuristic language detector for Arabic vs. English with a fast
    script-based check first, then langdetect as a fallback.
    """
    if not text:
        return default

    # If the text contains any Arabic-script characters, assume Arabic.
    if re.search(r"[\u0600-\u06FF]", text):
        return "ar"

    # If the text contains Latin letters, prefer English to avoid
    # langdetect misclassifying short English prompts as Arabic.
    if re.search(r"[A-Za-z]", text):
        return "en"

    try:
        lang = detect(text)
    except LangDetectException:
        return default
    if lang.startswith("ar"):
        return "ar"
    return "en"

logger = logging.getLogger('uvicorn.error')

nlp_router = APIRouter(
    prefix="/api/v1/nlp",
    tags=["api_v1", "nlp"],
)

KNOWN_DOCUMENT_TYPES = {"general", "military", "law", "finance"}
FILTERABLE_DOCUMENT_TYPES = KNOWN_DOCUMENT_TYPES - {"general"}


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

    app_settings = get_settings()
    generation_client = getattr(request.app, "generation_client", None)

    project_model = await ProjectModel.create_instance(
        db_client=request.app.db_client
    )

    chunk_model = await ChunkModel.create_instance(
        db_client=request.app.db_client
    )
    asset_model = await AssetModel.create_instance(
        db_client=request.app.db_client
    )
    target_asset_id = None

    project, status_code = await project_model.get_project_or_create_one(
        project_id=project_id,
        current_user=current_user,
        create_if_missing=False,
        is_private=None,
        require_owner=True,
    )

    if not project:
        response_status = status.HTTP_403_FORBIDDEN if status_code == "forbidden" else status.HTTP_404_NOT_FOUND
        response_signal = ResponseSignal.ACCESS_FORBIDDEN_ERROR.value if status_code == "forbidden" else ResponseSignal.PROJECT_NOT_FOUND_ERROR.value
        return JSONResponse(
            status_code=response_status,
            content={
                "signal": response_signal
            }
        )

    if push_request.asset_name:
        asset_record, record_exists = await asset_model.get_asset_record(
            asset_project_id=project.project_id,
            asset_name=push_request.asset_name,
            current_user=current_user,
        )
        if asset_record is None:
            signal = ResponseSignal.ACCESS_FORBIDDEN_ERROR.value if record_exists else ResponseSignal.FILE_ID_ERROR.value
            status_code_response = status.HTTP_403_FORBIDDEN if record_exists else status.HTTP_400_BAD_REQUEST
            detail = "File is private to another user." if record_exists else "No file found with the provided file identifier."
            return JSONResponse(
                status_code=status_code_response,
                content={
                    "signal": signal,
                    "detail": detail,
                }
            )
        target_asset_id = asset_record.asset_id

    # For indexing we don't have user-provided text to detect language from.
    # Default to the primary/default app language.
    template_language = app_settings.PRIMARY_LANG or app_settings.DEFAULT_LANG or "en"
    template_parser = TemplateParser(
        language=template_language,
        default_language=app_settings.DEFAULT_LANG or "en",
    )

    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=template_parser,
        search_client=getattr(request.app, "search_client", None),
        reranker_client=getattr(request.app, "reranker_client", None),
        reranker_max_candidates=getattr(request.app, "reranker_max_candidates", 0),
    )

    has_records = True
    page_no = 1
    inserted_items_count = 0
    idx = 0
    # create collection if not exists
    collection_name = nlp_controller.create_collection_name(project_id=project.project_id)

    do_reset_flag = bool(push_request.do_reset)
    _ = await request.app.vectordb_client.create_collection(
        collection_name=collection_name,
        embedding_size=request.app.embedding_client.embedding_size,
        do_reset=do_reset_flag,
    )
    # Avoid resetting the collection on each batch insertion.
    do_reset_flag = False

    # setup batching
    total_chunks_count = await chunk_model.get_total_chunks_count(
        project_id=project.project_id,
        asset_id=target_asset_id,
    )
    if total_chunks_count == 0:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.NO_FILES_ERROR.value,
                "detail": "No processed chunks found for the specified scope.",
            },
        )

    pbar = tqdm(total=total_chunks_count, desc="Vector Indexing", position=0)

    while has_records:
        page_chunks = await chunk_model.get_poject_chunks(
            project_id=project.project_id,
            page_no=page_no,
            asset_id=target_asset_id,
        )
        if len(page_chunks):
            page_no += 1
        
        if not page_chunks or len(page_chunks) == 0:
            has_records = False
            break

        chunks_ids =  [ c.chunk_id for c in page_chunks ]
        idx += len(page_chunks)
        
        is_inserted = await nlp_controller.index_into_vector_db(
            project=project,
            chunks=page_chunks,
            do_reset=do_reset_flag,
            chunks_ids=chunks_ids
        )

        if not is_inserted:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "signal": ResponseSignal.INSERT_INTO_VECTORDB_ERROR.value
                }
            )
            
        pbar.update(len(page_chunks))
        
        inserted_items_count += len(page_chunks)
        
    return JSONResponse(
        content={
            "signal": ResponseSignal.INSERT_INTO_VECTORDB_SUCCESS.value,
            "inserted_items_count": inserted_items_count
        }
    )

@nlp_router.get("/index/info/{project_id}")
async def get_project_index_info(
    request: Request,
    project_id: int,
    current_user: User = Depends(get_current_user),
):
    
    project_model = await ProjectModel.create_instance(
        db_client=request.app.db_client
    )

    project, status_code = await project_model.get_project_or_create_one(
        project_id=project_id,
        current_user=current_user,
        create_if_missing=True,
        is_private=None,
        require_owner=False,
    )

    if not project:
        response_status = status.HTTP_403_FORBIDDEN if status_code == "forbidden" else status.HTTP_404_NOT_FOUND
        response_signal = ResponseSignal.ACCESS_FORBIDDEN_ERROR.value if status_code == "forbidden" else ResponseSignal.PROJECT_NOT_FOUND_ERROR.value
        return JSONResponse(
            status_code=response_status,
            content={
                "signal": response_signal
            }
        )

    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=request.app.generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=request.app.template_parser,
        search_client=getattr(request.app, "search_client", None),
        reranker_client=getattr(request.app, "reranker_client", None),
        reranker_max_candidates=getattr(request.app, "reranker_max_candidates", 0),
    )

    collection_info =await nlp_controller.get_vector_db_collection_info(project=project)

    return JSONResponse(
        content={
            "signal": ResponseSignal.VECTORDB_COLLECTION_RETRIEVED.value,
            "collection_info": collection_info
        }
    )

@nlp_router.get("/conversations")
async def list_conversations(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    conversation_model = await ChatConversationModel.create_instance(
        db_client=request.app.db_client
    )

    conversations = await conversation_model.list_conversations(user_id=current_user.id)

    payload = [
        {
            "conversation_id": conversation.conversation_id,
            "title": conversation.conversation_title,
            "is_pinned": conversation.conversation_is_pinned,
            "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
            "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
        }
        for conversation in conversations
    ]

    return JSONResponse(
        content={
            "signal": ResponseSignal.CONVERSATIONS_FETCH_SUCCESS.value,
            "conversations": payload,
            "total": len(payload)
        }
    )

@nlp_router.get("/doc-types")
async def list_user_doc_types(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    async with request.app.db_client() as session:
        conditions = [Asset.asset_document_type.isnot(None)]
        if not getattr(current_user, "is_admin", False):
            conditions.append(
                or_(
                    Asset.asset_is_private.is_(False),
                    Asset.asset_user_id == current_user.id,
                )
            )

        result = await session.execute(
            select(Asset.asset_document_type)
            .where(*conditions)
            .distinct()
        )
        doc_types = sorted(
            {
                (value or "").strip()
                for (value,) in result.all()
                if value and value.strip()
            },
            key=lambda item: item.lower()
        )

    return JSONResponse(
        content={
            "signal": ResponseSignal.VECTORDB_SEARCH_SUCCESS.value,
            "doc_types": doc_types,
            "total": len(doc_types)
        }
    )
@nlp_router.get("/conversations/{conversation_id}/history")
async def get_conversation_history(
    request: Request,
    conversation_id: int,
    limit: Optional[int] = Query(None, ge=1, le=MAX_CONVERSATION_MESSAGES),
    current_user: User = Depends(get_current_user),
):
    conversation_model = await ChatConversationModel.create_instance(
        db_client=request.app.db_client
    )
    chat_history_model = await ChatHistoryModel.create_instance(
        db_client=request.app.db_client
    )

    conversation = await conversation_model.get_conversation(
        conversation_id=conversation_id,
        user_id=current_user.id
    )

    if not conversation:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "signal": ResponseSignal.PROJECT_NOT_FOUND_ERROR.value,
                "detail": "Conversation not found."
            }
        )

    if limit:
        history = await chat_history_model.get_recent_history_by_conversation(
            conversation_id=conversation_id,
            limit=limit
        )
    else:
        history = await chat_history_model.get_full_history_by_conversation(
            conversation_id=conversation_id
        )

    history_payload = [
        {
            "id": record.id,
            "prompt": record.prompt,
            "answer": record.answer,
            "model_key": record.model_key,
            "doc_types": record.doc_types,
            "timestamp": record.timestamp.isoformat() if record.timestamp else None,
            "response_time_ms": record.response_time_ms,
            "resources": getattr(record, "resources", None) or [],
        }
        for record in history
    ]

    return JSONResponse(
        content={
            "signal": ResponseSignal.CONVERSATION_HISTORY_SUCCESS.value,
            "conversation": {
                "conversation_id": conversation.conversation_id,
                "title": conversation.conversation_title,
                "is_pinned": conversation.conversation_is_pinned,
                "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
                "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
            },
            "history": history_payload,
        }
    )


@nlp_router.patch("/conversations/{conversation_id}")
async def rename_conversation(
    request: Request,
    conversation_id: int,
    update: ConversationUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    conversation_model = await ChatConversationModel.create_instance(
        db_client=request.app.db_client
    )
    conversation = await conversation_model.get_conversation(
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if not conversation:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "signal": ResponseSignal.CONVERSATION_HISTORY_SUCCESS.value,
                "detail": "Conversation not found.",
            },
        )

    new_title = None
    if update.title is not None:
        trimmed = update.title.strip()
        new_title = trimmed or "New Conversation"

    await conversation_model.update_conversation_fields(
        conversation_id=conversation_id,
        user_id=current_user.id,
        title=new_title,
        is_pinned=update.is_pinned,
    )

    return JSONResponse(
        content={
            "signal": ResponseSignal.CONVERSATION_HISTORY_SUCCESS.value,
            "conversation_id": conversation_id,
            "title": new_title if new_title is not None else conversation.conversation_title,
            "is_pinned": update.is_pinned if update.is_pinned is not None else conversation.conversation_is_pinned,
        }
    )


@nlp_router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    request: Request,
    conversation_id: int,
    current_user: User = Depends(get_current_user),
):
    conversation_model = await ChatConversationModel.create_instance(
        db_client=request.app.db_client
    )
    deleted = await conversation_model.delete_conversation(
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if not deleted:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "signal": ResponseSignal.USER_NOT_FOUND_ERROR.value,
                "detail": "Conversation not found.",
            },
        )

    return JSONResponse(
        content={
            "signal": ResponseSignal.FILE_DELETE_SUCCESS.value,
            "conversation_id": conversation_id,
        }
    )

@nlp_router.post("/index/search/{project_id}")
async def search_index(
    request: Request,
    project_id: int,
    search_request: SearchRequest,
    current_user: User = Depends(get_current_user),
):
    
    project_model = await ProjectModel.create_instance(
        db_client=request.app.db_client
    )

    project, status_code = await project_model.get_project_or_create_one(
        project_id=project_id,
        current_user=current_user,
        create_if_missing=False,
        is_private=None,
    )

    if not project:
        response_status = status.HTTP_403_FORBIDDEN if status_code == "forbidden" else status.HTTP_404_NOT_FOUND
        response_signal = ResponseSignal.ACCESS_FORBIDDEN_ERROR.value if status_code == "forbidden" else ResponseSignal.PROJECT_NOT_FOUND_ERROR.value
        return JSONResponse(
            status_code=response_status,
            content={
                "signal": response_signal
            }
        )

    asset_model = await AssetModel.create_instance(
        db_client=request.app.db_client
    )

    project_assets = await asset_model.get_all_project_assets(
        asset_project_id=project.project_id,
        asset_type=AssetTypeEnum.FILE.value,
        current_user=current_user,
    )
    accessible_asset_ids = {asset.asset_id for asset in project_assets}

    if not accessible_asset_ids:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.NO_FILES_ERROR.value,
                "detail": "No accessible files are available for search in this project."
            }
        )

    # Optional asset filter: restrict search to a single file when asset_id is provided.
    asset_filter = search_request.asset_id
    if asset_filter is not None:
        try:
            asset_filter_int = int(asset_filter)
        except (TypeError, ValueError):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "signal": ResponseSignal.FILE_ID_ERROR.value,
                    "detail": "Invalid asset_id filter.",
                },
            )

        if asset_filter_int not in accessible_asset_ids:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "signal": ResponseSignal.ACCESS_FORBIDDEN_ERROR.value,
                    "detail": "You do not have access to the requested file.",
                },
            )

        asset_ids_for_search = [asset_filter_int]
    else:
        asset_ids_for_search = list(accessible_asset_ids)

    # Simple keyword extraction from the query for lexical filtering
    query_text = search_request.text or ""
    keywords = [
        w.lower()
        for w in re.findall(r"\w+", query_text, flags=re.UNICODE)
        if len(w) > 3
    ]

    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=request.app.generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=request.app.template_parser,
        search_client=getattr(request.app, "search_client", None),
        reranker_client=getattr(request.app, "reranker_client", None),
        reranker_max_candidates=getattr(request.app, "reranker_max_candidates", 0),
    )

    results = await nlp_controller.search_vector_db_collection(
        project=project,
        text=search_request.text,
        limit=search_request.limit,
        asset_ids=asset_ids_for_search,
        keywords=keywords or None,
    )

    if results:
        results = await nlp_controller.rerank_documents(
            query=search_request.text or "",
            documents=results,
        )

    if not results:
        return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "signal": ResponseSignal.VECTORDB_SEARCH_ERROR.value
                }
            )
    
    return JSONResponse(
        content={
            "signal": ResponseSignal.VECTORDB_SEARCH_SUCCESS.value,
            "results": [ result.dict()  for result in results ]
        }
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

    project_model = await ProjectModel.create_instance(
        db_client=request.app.db_client
    )

    chunk_model = await ChunkModel.create_instance(
        db_client=request.app.db_client
    )

    asset_model = await AssetModel.create_instance(
        db_client=request.app.db_client
    )

    generation_clients = getattr(request.app, "generation_clients", {})
    generation_models = getattr(request.app, "generation_model_ids", {})
    default_model_key = getattr(request.app, "default_generation_model_key", None)
    default_generation_client = getattr(request.app, "generation_client", None)

    requested_model_key = (summarize_request.model or default_model_key or "best").lower()
    selected_generation_client = generation_clients.get(requested_model_key)

    if not selected_generation_client and summarize_request.model:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.RAG_ANSWER_ERROR.value,
                "detail": f"Unknown model '{summarize_request.model}'."
            }
        )

    generation_client = selected_generation_client or default_generation_client
    if generation_client is None:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "signal": ResponseSignal.RAG_ANSWER_ERROR.value,
                "detail": "Generation backend is not configured."
            }
        )

    model_key_used = requested_model_key if selected_generation_client else (default_model_key or "best")
    model_id_used = generation_models.get(model_key_used)

    project, status_code = await project_model.get_project_or_create_one(
        project_id=project_id,
        current_user=current_user,
        create_if_missing=False,
        is_private=None,
    )

    if not project:
        response_status = status.HTTP_403_FORBIDDEN if status_code == "forbidden" else status.HTTP_404_NOT_FOUND
        response_signal = ResponseSignal.ACCESS_FORBIDDEN_ERROR.value if status_code == "forbidden" else ResponseSignal.PROJECT_NOT_FOUND_ERROR.value
        return JSONResponse(
            status_code=response_status,
            content={
                "signal": response_signal
            }
        )

    target_asset_id = None
    selected_file = None
    accessible_asset_ids = []
    asset_label_lookup = {}
    asset_label_lookup_by_name = {}

    if summarize_request.file_id:
        asset_record, record_exists = await asset_model.get_asset_record(
            asset_project_id=project.project_id,
            asset_name=summarize_request.file_id,
            current_user=current_user,
        )

        if asset_record is None:
            signal = ResponseSignal.ACCESS_FORBIDDEN_ERROR.value if record_exists else ResponseSignal.FILE_ID_ERROR.value
            status_code_response = status.HTTP_403_FORBIDDEN if record_exists else status.HTTP_400_BAD_REQUEST
            detail = "File is private to another user." if record_exists else "No file found with the provided file identifier."
            return JSONResponse(
                status_code=status_code_response,
                content={
                    "signal": signal,
                    "detail": detail
                }
            )

        target_asset_id = asset_record.asset_id
        selected_file = asset_record.asset_name
        accessible_asset_ids = [asset_record.asset_id]
        display_name = get_asset_display_name(asset_record) or asset_record.asset_name
        asset_label_lookup[asset_record.asset_id] = display_name
        asset_label_lookup_by_name[asset_record.asset_name] = display_name

    max_chunks = None
    if summarize_request.max_chunks and summarize_request.max_chunks > 0:
        max_chunks = summarize_request.max_chunks

    if target_asset_id is None:
        project_assets = await asset_model.get_all_project_assets(
            asset_project_id=project.project_id,
            asset_type=AssetTypeEnum.FILE.value,
            current_user=current_user,
        )
        accessible_asset_ids = []
        for record in project_assets:
            accessible_asset_ids.append(record.asset_id)
            display_name = get_asset_display_name(record) or record.asset_name
            asset_label_lookup[record.asset_id] = display_name
            asset_label_lookup_by_name[record.asset_name] = display_name

    if not accessible_asset_ids:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.NO_FILES_ERROR.value,
                "detail": "No accessible files are available for summarization."
            }
        )

    # Always load all chunks for summarization so that very large
    # documents are covered end-to-end. We rely on hierarchical
    # summarization and section-level clamping later to stay within
    # the model's context window.
    chunks = await chunk_model.get_project_chunks_for_summary(
        project_id=project.project_id,
        asset_ids=accessible_asset_ids,
        limit=None,
    )

    if not chunks:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.SUMMARY_GENERATION_ERROR.value,
                "detail": "No processed chunks found for summarization. Ensure the project data is processed first."
            }
        )

    total_chunks = len(chunks)

    # Optional focus-based filtering: if user provides a focus text and we have many chunks,
    # restrict to chunks that contain focus keywords to keep the summary manageable and relevant.
    focus_text = (summarize_request.focus or "").strip()
    if focus_text and total_chunks > 100:
        keywords = [
            word.lower()
            for word in focus_text.split()
            if len(word) > 3
        ]
        if keywords:
            filtered_chunks = [
                chunk
                for chunk in chunks
                if any(
                    kw in (getattr(chunk, "chunk_text", "") or "").lower()
                    for kw in keywords
                )
            ]
            # Use filtered chunks only if we still have a reasonable amount of context.
            if len(filtered_chunks) >= 10:
                chunks = filtered_chunks
                total_chunks = len(chunks)

    # Keep track of the original chunks for metadata (chunk_ids, counts),
    # but allow a separate list of "summary input chunks" that may pass through
    # a hierarchical summarization step.
    source_chunks = chunks

    summary_max_tokens = (
        summarize_request.max_output_tokens
        or app_settings.SUMMARY_DEFAULT_MAX_TOKENS
        or app_settings.GENERATION_DAFAULT_MAX_TOKENS
    )

    # Determine template language for summary:
    # Detect based on the document content (first few chunks). If no
    # reasonable sample is available, fall back to app settings.
    sample_text_parts: List[str] = []
    for chunk in source_chunks[:3]:
        chunk_text = getattr(chunk, "chunk_text", "") or ""
        if chunk_text:
            sample_text_parts.append(chunk_text)
    sample_text = " ".join(sample_text_parts)[:2000] if sample_text_parts else ""

    template_language = detect_language_or_default(
        sample_text,
        app_settings.PRIMARY_LANG or app_settings.DEFAULT_LANG or "en",
    )
    template_parser = TemplateParser(
        language=template_language,
        default_language=app_settings.DEFAULT_LANG or "en",
    )

    # Use a fresh NLPController with the per-request template language,
    # so that selecting Arabic in the UI actually switches the summary prompt.
    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=template_parser,
    )

    # Hierarchical summarization for very large documents:
    # - First, generate summaries for sections of chunks.
    # - Then, summarize those section summaries to produce a document-level summary.
    summary_input_chunks = chunks
    HIERARCHICAL_THRESHOLD = 120  # number of chunks above which we switch to hierarchical
    SECTION_SIZE = 10  # chunks per section
    MAX_SECTION_SUMMARIES = 20   # clamp at the section-summary level to this many

    if total_chunks > HIERARCHICAL_THRESHOLD:
        section_summaries: List[str] = []
        section_max_tokens = min(summary_max_tokens, 256)

        # First pass: summarize each logical section so that *all* parts of the
        # document contribute to some section-level summary.
        for i in range(0, total_chunks, SECTION_SIZE):
            section = chunks[i : i + SECTION_SIZE]
            if not section:
                continue

            section_summary, _ = nlp_controller.summarize_chunks(
                chunks=section,
                focus=summarize_request.focus,
                max_output_tokens=section_max_tokens,
                asset_labels=asset_label_lookup if asset_label_lookup else None,
                asset_labels_by_name=asset_label_lookup_by_name if asset_label_lookup_by_name else None,
                stream=False,
                collector=None,
            )

            if section_summary and isinstance(section_summary, str):
                section_summaries.append(section_summary.strip())

        if section_summaries:
            # If there are too many section summaries to fit comfortably into the
            # model context, subsample them *evenly across the document* so that
            # the final summary still represents the whole file rather than only
            # the beginning.
            if len(section_summaries) > MAX_SECTION_SUMMARIES:
                step = len(section_summaries) / MAX_SECTION_SUMMARIES
                selected = []
                for idx in range(MAX_SECTION_SUMMARIES):
                    pos = int(idx * step)
                    if pos >= len(section_summaries):
                        pos = len(section_summaries) - 1
                    selected.append(section_summaries[pos])
                section_summaries = selected

            # Build synthetic "chunks" from section summaries for the final pass.
            summary_input_chunks = [
                SimpleNamespace(
                    chunk_text=text,
                    chunk_order=idx + 1,
                    chunk_metadata={"section_index": idx + 1},
                )
                for idx, text in enumerate(section_summaries)
            ]

    summary_model = await SummaryModel.create_instance(
        db_client=request.app.db_client
    )

    chunk_ids = [
        chunk.chunk_id
        for chunk in source_chunks
        if getattr(chunk, "chunk_id", None) is not None
    ]

    stream_enabled = (
        summarize_request.stream
        if summarize_request.stream is not None
        else True
    )
    collector = {"output": [], "reasoning": []} if stream_enabled else None

    summary_output, full_prompt = nlp_controller.summarize_chunks(
        chunks=summary_input_chunks,
        focus=summarize_request.focus,
        max_output_tokens=summary_max_tokens,
        asset_labels=asset_label_lookup if asset_label_lookup else None,
        asset_labels_by_name=asset_label_lookup_by_name if asset_label_lookup_by_name else None,
        stream=stream_enabled,
        collector=collector,
    )

    if stream_enabled:
        if summary_output is None:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "signal": ResponseSignal.SUMMARY_GENERATION_ERROR.value,
                    "detail": "Unable to start streaming summary response.",
                },
            )

        async def summary_event_stream():
            try:
                yield json.dumps({
                    "signal": ResponseSignal.SUMMARY_STREAM_START.value,
                    "file_id": selected_file,
                    "focus": summarize_request.focus,
                    "max_output_tokens": summary_max_tokens,
                    "used_chunks": len(chunks),
                    "model": model_key_used,
                    "model_id": model_id_used,
                }) + "\n"

                for chunk in summary_output:
                    if chunk:
                        yield json.dumps({
                            "signal": ResponseSignal.SUMMARY_STREAM_DELTA.value,
                            "delta": chunk,
                        }) + "\n"
            finally:
                final_summary = "".join(collector.get("output", [])) if collector else ""
                final_summary = final_summary.strip()
                signal_value = ResponseSignal.SUMMARY_GENERATION_SUCCESS.value if final_summary else ResponseSignal.SUMMARY_GENERATION_ERROR.value

                if final_summary:
                        await summary_model.create_summary(
                            user_id=current_user.id,
                            project_id=project.project_id,
                            asset_id=target_asset_id,
                            summary_text=final_summary,
                            request_payload={
                                "file_id": summarize_request.file_id,
                                "max_chunks": summarize_request.max_chunks,
                                "focus": summarize_request.focus,
                                "requested_max_output_tokens": summarize_request.max_output_tokens,
                                "max_output_tokens_used": summary_max_tokens,
                                "model": model_key_used,
                                "output_lang": summarize_request.output_lang,
                            },
                        chunk_ids=chunk_ids,
                        chunk_count=len(chunks),
                        prompt_text=full_prompt,
                        max_output_tokens=summary_max_tokens,
                    )

                payload = {
                    "signal": signal_value,
                    "summary": final_summary,
                    "used_chunks": len(chunks),
                    "file_id": selected_file,
                    "focus": summarize_request.focus,
                    "max_output_tokens": summary_max_tokens,
                    "full_prompt": full_prompt,
                    "model": model_key_used,
                    "model_id": model_id_used,
                }
                yield json.dumps(payload) + "\n"

        return StreamingResponse(summary_event_stream(), media_type="application/json")

    if not summary_output:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.SUMMARY_GENERATION_ERROR.value,
                "detail": "The summarization provider did not return any content."
            }
        )

    summary = summary_output

    await summary_model.create_summary(
        user_id=current_user.id,
        project_id=project.project_id,
        asset_id=target_asset_id,
        summary_text=summary,
        request_payload={
            "file_id": summarize_request.file_id,
            "max_chunks": summarize_request.max_chunks,
            "focus": summarize_request.focus,
            "requested_max_output_tokens": summarize_request.max_output_tokens,
            "max_output_tokens_used": summary_max_tokens,
            "model": model_key_used,
            "output_lang": summarize_request.output_lang,
        },
        chunk_ids=chunk_ids,
        chunk_count=len(chunks),
        prompt_text=full_prompt,
        max_output_tokens=summary_max_tokens,
    )

    return JSONResponse(
        content={
            "signal": ResponseSignal.SUMMARY_GENERATION_SUCCESS.value,
            "summary": summary,
            "used_chunks": len(chunks),
            "file_id": selected_file,
            "focus": summarize_request.focus,
            "max_output_tokens": summary_max_tokens,
            "full_prompt": full_prompt,
            "model": model_key_used,
            "model_id": model_id_used,
        }
    )


@nlp_router.get("/summary")
async def list_summaries(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
):
    async with request.app.db_client() as session:
        result = await session.execute(
            select(SummaryRecord, Asset)
            .outerjoin(Asset, SummaryRecord.asset_id == Asset.asset_id)
            .where(SummaryRecord.user_id == current_user.id)
            .order_by(SummaryRecord.created_at.desc())
            .limit(limit)
        )
        rows = result.all()

    summaries = []
    for summary_record, asset in rows:
        asset_name = None
        asset_doc_type = None
        if asset is not None:
            asset_name = getattr(asset, "asset_name", None)
            config = getattr(asset, "asset_config", None) or {}
            original_name = config.get("original_filename")
            asset_name = original_name or asset_name
            asset_doc_type = getattr(asset, "asset_document_type", None)

        payload = summary_record.request_payload or {}

        summaries.append(
            {
                "summary_id": summary_record.summary_id,
                "file_id": summary_record.asset_id,
                "file_name": asset_name,
                "doc_type": asset_doc_type,
                "model": payload.get("model"),
                "focus": payload.get("focus"),
                "created_at": summary_record.created_at.isoformat()
                if summary_record.created_at
                else None,
            }
        )

    return JSONResponse(
        content={
            "summaries": summaries,
            "total": len(summaries),
        }
    )


@nlp_router.get("/summary/{summary_id}")
async def get_summary(
    request: Request,
    summary_id: int,
    current_user: User = Depends(get_current_user),
):
    async with request.app.db_client() as session:
        result = await session.execute(
            select(SummaryRecord, Asset)
            .outerjoin(Asset, SummaryRecord.asset_id == Asset.asset_id)
            .where(SummaryRecord.summary_id == summary_id)
        )
        row = result.first()

    if not row:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "signal": ResponseSignal.USER_NOT_FOUND_ERROR.value,
                "detail": f"Summary with id {summary_id} not found.",
            },
        )

    summary_record, asset = row

    # Only the summary owner or an admin can view the full summary.
    if summary_record.user_id != getattr(current_user, "id", None) and not getattr(
        current_user, "is_admin", False
    ):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "signal": ResponseSignal.ACCESS_FORBIDDEN_ERROR.value,
                "detail": "You do not have access to this summary.",
            },
        )

    asset_name = None
    asset_doc_type = None
    if asset is not None:
        asset_name = getattr(asset, "asset_name", None)
        config = getattr(asset, "asset_config", None) or {}
        original_name = config.get("original_filename")
        asset_name = original_name or asset_name
        asset_doc_type = getattr(asset, "asset_document_type", None)

    payload = summary_record.request_payload or {}

    return JSONResponse(
        content={
            "summary_id": summary_record.summary_id,
            "summary": summary_record.summary_text,
            "file_id": summary_record.asset_id,
            "file_name": asset_name,
            "doc_type": asset_doc_type,
            "model": payload.get("model"),
            "focus": payload.get("focus"),
            "max_chunks": payload.get("max_chunks"),
            "max_output_tokens": payload.get("requested_max_output_tokens"),
            "created_at": summary_record.created_at.isoformat()
            if summary_record.created_at
            else None,
            "prompt_text": summary_record.prompt_text,
            "max_output_tokens_used": summary_record.max_output_tokens,
        }
    )


@nlp_router.delete("/summary/{summary_id}")
async def delete_summary(
    request: Request,
    summary_id: int,
    current_user: User = Depends(get_current_user),
):
    summary_model = await SummaryModel.create_instance(
        db_client=request.app.db_client
    )
    summary_record = await summary_model.get_summary_by_id(summary_id)

    if not summary_record:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "signal": ResponseSignal.USER_NOT_FOUND_ERROR.value,
                "detail": f"Summary with id {summary_id} not found.",
            },
        )

    if summary_record.user_id != getattr(current_user, "id", None) and not getattr(
        current_user, "is_admin", False
    ):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "signal": ResponseSignal.ACCESS_FORBIDDEN_ERROR.value,
                "detail": "You do not have access to delete this summary.",
            },
        )

    deleted = await summary_model.delete_summary(summary_id=summary_id)
    if not deleted:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "signal": ResponseSignal.USER_NOT_FOUND_ERROR.value,
                "detail": f"Summary with id {summary_id} not found.",
            },
        )

    return JSONResponse(
        content={
            "signal": ResponseSignal.SUMMARY_DELETE_SUCCESS.value,
            "summary_id": summary_id,
        }
    )


@nlp_router.post("/summaries/bulk-delete")
async def delete_summaries_bulk(
    request: Request,
    payload: DeleteSummariesRequest,
    current_user: User = Depends(get_current_user),
):
    summary_ids = payload.summary_ids or []
    if not summary_ids:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.USER_NOT_FOUND_ERROR.value,
                "detail": "No summary ids provided.",
            },
        )

    summary_model = await SummaryModel.create_instance(
        db_client=request.app.db_client
    )

    deleted_ids = []
    for summary_id in summary_ids:
        summary_record = await summary_model.get_summary_by_id(summary_id)
        if not summary_record:
            continue
        if summary_record.user_id != getattr(current_user, "id", None) and not getattr(
            current_user, "is_admin", False
        ):
            continue
        deleted = await summary_model.delete_summary(summary_id=summary_id)
        if deleted:
            deleted_ids.append(summary_id)

    return JSONResponse(
        content={
            "signal": ResponseSignal.SUMMARY_DELETE_SUCCESS.value,
            "deleted_ids": deleted_ids,
        }
    )

