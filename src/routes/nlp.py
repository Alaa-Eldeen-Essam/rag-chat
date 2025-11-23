from fastapi import APIRouter, status, Request, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from routes.schemes.nlp import PushRequest, SearchRequest, SummarizeRequest, ConversationUpdateRequest
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

    await conversation_model.update_conversation_title(
        conversation_id=conversation_id,
        user_id=current_user.id,
        title=update.title.strip() or "New Conversation",
    )

    return JSONResponse(
        content={
            "signal": ResponseSignal.CONVERSATION_HISTORY_SUCCESS.value,
            "conversation_id": conversation_id,
            "title": update.title,
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
    )

    results = await nlp_controller.search_vector_db_collection(
        project=project,
        text=search_request.text,
        limit=search_request.limit,
        asset_ids=asset_ids_for_search,
        keywords=keywords or None,
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

    # Collect all accessible assets across projects (own + public, or all for admins)
    all_assets = await asset_model.get_all_accessible_assets(
        asset_type=AssetTypeEnum.FILE.value,
        current_user=current_user,
    )
    asset_label_lookup = {}
    asset_label_lookup_by_name = {}
    accessible_asset_ids = set()
    assets_by_project_id = {}
    asset_to_project: dict[int, int] = {}
    for asset in all_assets:
        display_name = get_asset_display_name(asset) or asset.asset_name
        asset_label_lookup[asset.asset_id] = display_name
        asset_label_lookup_by_name[asset.asset_name] = display_name
        accessible_asset_ids.add(asset.asset_id)
        assets_by_project_id.setdefault(asset.asset_project_id, []).append(asset)
        asset_to_project[asset.asset_id] = asset.asset_project_id

    if not accessible_asset_ids:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.NO_FILES_ERROR.value,
                "detail": "No accessible files are available for search.",
            },
        )

    generation_clients = getattr(request.app, "generation_clients", {})
    generation_models = getattr(request.app, "generation_model_ids", {})
    default_model_key = getattr(request.app, "default_generation_model_key", None)
    default_generation_client = getattr(request.app, "generation_client", None)

    requested_model_key = (search_request.model or default_model_key or "best").lower()
    generation_client = generation_clients.get(requested_model_key) or default_generation_client
    model_key_used = requested_model_key if generation_client else default_model_key or "best"
    generation_client = generation_client or default_generation_client

    template_language = detect_language_or_default(
        search_request.text,
        app_settings.PRIMARY_LANG or app_settings.DEFAULT_LANG or "en",
    )
    template_parser = TemplateParser(
        language=template_language,
        default_language=app_settings.DEFAULT_LANG or "en",
    )

    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=template_parser,
    )

    chat_history_model = await ChatHistoryModel.create_instance(
        db_client=request.app.db_client
    )
    conversation_model = await ChatConversationModel.create_instance(
        db_client=request.app.db_client
    )

    conversation = None
    if search_request.conversation_id:
        conversation = await conversation_model.get_conversation(
            conversation_id=search_request.conversation_id,
            user_id=current_user.id,
        )
        if not conversation:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "signal": ResponseSignal.PROJECT_NOT_FOUND_ERROR.value,
                    "detail": "Conversation not found."
                }
            )
    else:
        conversation = await conversation_model.create_conversation(
            user_id=current_user.id,
            initial_prompt=search_request.text
        )

    explicit_doc_type = (search_request.doc_type or "").strip().lower() if hasattr(search_request, "doc_type") else ""
    if not explicit_doc_type or explicit_doc_type == "all":
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.VECTORDB_SEARCH_ERROR.value,
                "detail": "You must select a document type before asking questions.",
            },
        )
    doc_type_filter = [explicit_doc_type]
    asset_filter = search_request.asset_id
    asset_filters: Optional[List[int]] = None
    if getattr(search_request, "asset_ids", None):
        try:
            asset_filters = [
                int(aid)
                for aid in (search_request.asset_ids or [])
                if aid is not None
            ]
        except (TypeError, ValueError):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "signal": ResponseSignal.FILE_ID_ERROR.value,
                    "detail": "Invalid asset_ids filter.",
                },
            )

    recent_history = await chat_history_model.get_recent_history_by_conversation(
        conversation_id=conversation.conversation_id,
        limit=5
    )

    # Build chat history for the LLM, but only reuse turns that are
    # compatible with the current doc_type / file filters. This keeps
    # follow-ups on the same scope rich, while avoiding leaking context
    # from questions asked under different document types or files.
    chat_messages = []
    last_user_question: Optional[str] = None
    for record in recent_history:
        record_doc_types = getattr(record, "doc_types", None) or []
        # If no filters are active, reuse all history.
        if not explicit_doc_type and asset_filter is None:
            chat_messages.append(
                {
                    "prompt": record.prompt,
                    "answer": record.answer,
                }
            )
            if record.prompt:
                last_user_question = record.prompt
            continue

        compatible = True

        # DocType compatibility: if an explicit doc_type is set now, only
        # reuse history that was created under the same doc_type, or under
        # the generic "all" scope.
        if explicit_doc_type:
            lowered_record_types = {str(dt).strip().lower() for dt in record_doc_types}
            if "all" not in lowered_record_types and explicit_doc_type not in lowered_record_types:
                compatible = False

        # Asset/file compatibility: if a file filter is active, only reuse
        # history entries that were associated with the same asset.
        if compatible and asset_filter is not None:
            tag = f"asset:{asset_filter}"
            if tag not in record_doc_types:
                compatible = False

        if compatible:
            chat_messages.append(
                {
                    "prompt": record.prompt,
                    "answer": record.answer,
                }
            )
            if record.prompt:
                last_user_question = record.prompt

    collector = {"output": [], "reasoning": []} if search_request.stream else None

    # Simple keyword extraction from the query for lexical re-ranking
    query_text = search_request.text or ""
    keywords = [
        w.lower()
        for w in re.findall(r"\w+", query_text, flags=re.UNICODE)
        if len(w) > 3
    ]

    # For retrieval, embed primarily the current question text. When the
    # last user question in the same scoped conversation is strongly
    # similar to the current question (embedding-based), treat the new
    # query as a follow-up and build a combined retrieval text so that
    # retrieval stays on-topic in multi-turn flows without relying on
    # language-specific heuristics.
    retrieval_text = search_request.text or ""
    embedding_client = getattr(request.app, "embedding_client", None)

    def _cosine_similarity(a: List[float], b: List[float]) -> Optional[float]:
        if not a or not b or len(a) != len(b):
            return None
        dot = 0.0
        na = 0.0
        nb = 0.0
        for x, y in zip(a, b):
            dot += x * y
            na += x * x
            nb += y * y
        if na <= 0.0 or nb <= 0.0:
            return None
        return dot / (math.sqrt(na) * math.sqrt(nb))

    if (
        embedding_client is not None
        and last_user_question
        and retrieval_text
        and last_user_question.strip()
        and retrieval_text.strip()
    ):
        try:
            vecs = embedding_client.embed_text(
                text=[last_user_question, retrieval_text],
                document_type=DocumentTypeEnum.QUERY.value,
            )
            if isinstance(vecs, list) and len(vecs) >= 2:
                v_last, v_now = vecs[0], vecs[1]
                sim = _cosine_similarity(v_last, v_now)
                # Treat similarity above this threshold as a follow-up.
                if sim is not None and sim >= 0.4:
                    retrieval_text = f"{last_user_question}\n\n{retrieval_text}"
        except Exception as exc:
            logger.error("Follow-up similarity check failed: %s", exc)

    # Ensure requested asset filter(s) are within the user's accessible scope
    if asset_filters:
        invalid_ids = [aid for aid in asset_filters if aid not in accessible_asset_ids]
        if invalid_ids:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "signal": ResponseSignal.ACCESS_FORBIDDEN_ERROR.value,
                    "detail": "You do not have access to one or more requested files.",
                },
            )
    elif asset_filter is not None:
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
    start_time = time.perf_counter()

    # Build project -> asset_ids mapping for search
    asset_ids_by_project: dict[int, list[int]] = {}
    if asset_filters:
        for aid in asset_filters:
            project_for_asset = asset_to_project.get(aid)
            if project_for_asset is not None:
                asset_ids_by_project.setdefault(project_for_asset, []).append(aid)
    elif asset_filter is not None:
        asset_filter_int = int(asset_filter)
        project_for_asset = asset_to_project.get(asset_filter_int)
        if project_for_asset is not None:
            asset_ids_by_project[project_for_asset] = [asset_filter_int]
    else:
        for pid, assets in assets_by_project_id.items():
            asset_ids_by_project[pid] = [a.asset_id for a in assets]

    retrieved_documents: list[Any] = []
    if asset_ids_by_project:
        for pid, asset_ids_for_project in asset_ids_by_project.items():
            project_stub = SimpleNamespace(project_id=pid)
            results = await nlp_controller.search_vector_db_collection(
                project=project_stub,
                text=retrieval_text,
                limit=search_request.limit,
                doc_types=doc_type_filter if doc_type_filter else None,
                asset_ids=asset_ids_for_project,
                keywords=keywords or None,
            )
            if results:
                retrieved_documents.extend(results)

    # Attempt deterministic direct extraction (e.g. dates / reasons) before
    # delegating to the LLM, so simple factual questions behave consistently.
    question_type = nlp_controller._detect_question_type(search_request.text)
    direct_hint = nlp_controller._try_extract_direct_answer(
        query=search_request.text,
        documents=retrieved_documents or [],
        question_type=question_type,
    )

    # Try to resolve a human-readable label for the document that most likely
    # contains the direct hint (for example, the original filename). This
    # allows deterministic answers like "according to <document name>" instead
    # of the more generic "according to the documents".
    doc_label_for_hint: Optional[str] = None
    if direct_hint and retrieved_documents:
        chosen_doc = None
        for doc in retrieved_documents:
            text_value = getattr(doc, "text", "") or ""
            if direct_hint in text_value:
                chosen_doc = doc
                break
        if chosen_doc is None:
            chosen_doc = retrieved_documents[0]

        try:
            doc_label_for_hint = nlp_controller._resolve_document_label(
                getattr(chosen_doc, "metadata", None),
                fallback_label="Document 1",
                asset_labels=asset_label_lookup if asset_label_lookup else None,
                asset_labels_by_name=asset_label_lookup_by_name if asset_label_lookup_by_name else None,
                asset_id_hint=None,
            )
        except Exception:
            doc_label_for_hint = None

    # For clear "when / متى" questions where we can reliably extract a concrete
    # date from the retrieved documents, short-circuit and answer directly for
    # non-streaming calls. For "why / لماذا" we prefer to pass the extracted
    # hint into the LLM so it can clean up / enrich the answer instead of
    # returning the raw snippet.
    answer_result = None
    full_prompt = None
    chat_history = None

    if not search_request.stream and direct_hint and question_type == "when":
        has_arabic = bool(re.search(r"[\u0600-\u06FF]", search_request.text or ""))
        if doc_label_for_hint:
            prefix_ar = f'وفقاً للمستند "{doc_label_for_hint}"، '
            prefix_en = f'According to the document "{doc_label_for_hint}", '
        else:
            prefix_ar = "وفقاً للمستندات، "
            prefix_en = "According to the documents, "

        if has_arabic:
            answer_result = f"{prefix_ar}كان ذلك في {direct_hint}."
        else:
            answer_result = f"{prefix_en}this occurred on {direct_hint}."
    else:
        answer_result, full_prompt, chat_history = await nlp_controller.generate_rag_answer_from_documents(
            retrieved_documents=retrieved_documents,
            query=search_request.text,
            chat_messages=chat_messages,
            stream=bool(search_request.stream),
            collector=collector,
            asset_labels=asset_label_lookup if asset_label_lookup else None,
            asset_labels_by_name=asset_label_lookup_by_name if asset_label_lookup_by_name else None,
            direct_hint=direct_hint,
        )

    # Basic retrieval stats for later analytics
    retrieved_chunks_count = len(retrieved_documents) if retrieved_documents else 0
    retrieved_doc_types: List[str] = []
    retrieved_asset_ids: List[int] = []
    if retrieved_documents:
        for doc in retrieved_documents:
            metadata = getattr(doc, "metadata", None)
            doc_type_value = None
            asset_id_value = None
            if isinstance(metadata, dict):
                doc_type_value = metadata.get("doc_type") or metadata.get("document_type")
                asset_id_value = metadata.get("asset_id")
            elif metadata is not None and hasattr(metadata, "get"):
                doc_type_value = metadata.get("doc_type") or metadata.get("document_type")
                asset_id_value = metadata.get("asset_id")
            if isinstance(doc_type_value, str):
                dt = doc_type_value.strip().lower()
                if dt and dt not in retrieved_doc_types:
                    retrieved_doc_types.append(dt)
            if asset_id_value is not None:
                try:
                    aid_int = int(asset_id_value)
                    if aid_int not in retrieved_asset_ids:
                        retrieved_asset_ids.append(aid_int)
                except (TypeError, ValueError):
                    continue

    no_answer_from_docs = answer_result is None and (full_prompt is None or chat_history is None)

    # Build a lightweight evidence corpus (lowercased) for post-hoc
    # checking that the final answer is actually grounded in retrieved
    # text. This is used only for non-streaming calls.
    evidence_corpus = ""
    if retrieved_documents:
        parts: List[str] = []
        for doc in retrieved_documents:
            parts.append((getattr(doc, "text", "") or "").lower())
        evidence_corpus = " ".join(parts)

    def build_sources(max_sources: int = 15) -> List[Dict[str, str]]:
        sources: List[Dict[str, str]] = []
        # Deduplicate by chunk_id when available, instead of by (file, page).
        seen_ids: set[int] = set()

        if not retrieved_documents:
            return sources

        for idx, doc in enumerate(retrieved_documents):
            text = getattr(doc, "text", "") or ""
            metadata = getattr(doc, "metadata", None)
            meta_dict: Dict[str, Any] = {}
            if isinstance(metadata, dict):
                meta_dict = metadata
            elif metadata is not None and hasattr(metadata, "dict"):
                try:
                    maybe = metadata.dict()  # type: ignore[call-arg]
                    if isinstance(maybe, dict):
                        meta_dict = maybe
                except Exception:
                    meta_dict = {}

            asset_id_value = meta_dict.get("asset_id")
            file_name = (
                meta_dict.get("original_filename")
                or meta_dict.get("source_name")
                or (
                    asset_label_lookup.get(int(asset_id_value))
                    if asset_label_lookup and asset_id_value is not None
                    else None
                )
                or f"Document {idx + 1}"
            )

            page = meta_dict.get("page") or meta_dict.get("page_number")
            section = meta_dict.get("section") or meta_dict.get("heading")
            page_no: Optional[int] = None
            try:
                if page is not None:
                    page_no = int(page)
            except (TypeError, ValueError):
                page_no = None

            if page_no is not None:
                location = f"Page {page_no}"
            elif section:
                location = str(section)
            else:
                location = f"Excerpt {idx + 1}"

            # Use chunk_id (if present) to avoid collapsing multiple chunks
            # from the same file & page into a single source.
            chunk_id_value = meta_dict.get("chunk_id")
            key_id: int
            try:
                key_id = int(chunk_id_value) if chunk_id_value is not None else idx + 1
            except (TypeError, ValueError):
                key_id = idx + 1
            if key_id in seen_ids:
                continue
            seen_ids.add(key_id)

            # Use the full chunk text as the snippet so that
            # resources expose the complete retrieved evidence.
            snippet = (text or "").strip()

            sources.append(
                {
                    "file_name": str(file_name),
                    "location": location,
                    "page": page_no,
                    "excerpt_index": idx + 1,
                    "snippet": snippet,
                }
            )

            if len(sources) >= max_sources:
                break

        return sources

    answer_sources = build_sources()

    def compose_final_answer(store: dict) -> str:
        output_text = "".join(store.get("output", [])) if store else ""
        reasoning_text = "".join(store.get("reasoning", [])) if store else ""

        output_text = output_text.strip()
        reasoning_text = reasoning_text.strip()

        if output_text and reasoning_text:
            return f"{output_text}\n\nReasoning:\n{reasoning_text}"
        if output_text:
            return output_text
        if reasoning_text:
            return reasoning_text
        return ""

    def looks_like_refusal(text: str) -> bool:
        if not text:
            return False
        t = text.strip()
        patterns = [
            "لا يمكن تحديد",
            "لا توجد معلومات كافية",
            "لا أستطيع الإجابة",
            "المعلومات غير كافية",
            "cannot determine",
            "not enough information",
            "cannot be determined",
        ]
        return any(pat in t for pat in patterns)

    def clean_display_hint(text: str) -> str:
        """
        Light cleaning for direct_hint before showing it to the user so that
        obvious OCR artifacts or formatting issues are less distracting.
        """
        if not text:
            return ""
        t = text.strip()
        # Collapse whitespace and strip common surrounding quotes.
        t = re.sub(r"\s+", " ", t)
        t = t.strip('\"“”\'')
        return t

    history_filter = doc_type_filter.copy() if doc_type_filter else []
    if asset_filter is not None:
        history_filter.append(f"asset:{asset_filter}")

    fallback_answer = (
        "I don't have enough information in your indexed documents to answer this question."
    )

    if search_request.stream:
        async def event_stream():
            if no_answer_from_docs:
                yield json.dumps({
                    "signal": ResponseSignal.RAG_ANSWER_STREAM_START.value,
                    "conversation_id": conversation.conversation_id,
                    "conversation_title": conversation.conversation_title,
                    "model": model_key_used,
                    "model_id": generation_models.get(model_key_used),
                }) + "\n"

                yield json.dumps({
                    "signal": ResponseSignal.RAG_ANSWER_STREAM_DELTA.value,
                    "delta": fallback_answer
                }) + "\n"

                response_time_ms = int((time.perf_counter() - start_time) * 1000)
                history_record = await chat_history_model.create_history(
                    user_id=current_user.id,
                    conversation_id=conversation.conversation_id,
                    prompt=search_request.text,
                    answer=fallback_answer,
                    model_key=model_key_used,
                    doc_types=history_filter or ["all"],
                    response_time_ms=response_time_ms,
                    fallback_used=True,
                    retrieved_chunks=retrieved_chunks_count,
                    retrieved_doc_types=retrieved_doc_types or None,
                    retrieved_asset_ids=retrieved_asset_ids or None,
                    resources=[],
                )
                await conversation_model.touch_conversation(conversation.conversation_id)

                payload = {
                    "signal": ResponseSignal.RAG_ANSWER_SUCCESS.value,
                    "answer": fallback_answer,
                    "full_prompt": None,
                    "chat_history": [],
                    "conversation_id": conversation.conversation_id,
                    "conversation_title": conversation.conversation_title,
                    "document_types": history_filter or ["all"],
                    "model": model_key_used,
                    "model_id": generation_models.get(model_key_used),
                    "asset_id": asset_filter,
                    "message_id": history_record.id,
                    "sources": [],
                }
                yield json.dumps(payload) + "\n"
            else:
                try:
                    yield json.dumps({
                        "signal": ResponseSignal.RAG_ANSWER_STREAM_START.value,
                        "conversation_id": conversation.conversation_id,
                        "conversation_title": conversation.conversation_title,
                        "model": model_key_used,
                        "model_id": generation_models.get(model_key_used),
                    }) + "\n"

                    for chunk in answer_result:
                        if chunk:
                            yield json.dumps({
                                "signal": ResponseSignal.RAG_ANSWER_STREAM_DELTA.value,
                                "delta": chunk
                            }) + "\n"
                finally:
                    final_answer = compose_final_answer(collector)

                    # If we extracted a direct hint for a "why / لماذا" question
                    # but the model still produced a refusal-style answer, prefer
                    # a deterministic answer built directly from the hint instead.
                    if direct_hint and question_type == "why" and looks_like_refusal(final_answer):
                        has_arabic = bool(re.search(r"[\u0600-\u06FF]", search_request.text or ""))
                        hint_for_display = clean_display_hint(direct_hint)
                        if doc_label_for_hint:
                            prefix_ar = f'وفقاً للمستند "{doc_label_for_hint}"، '
                            prefix_en = f'According to the document "{doc_label_for_hint}", '
                        else:
                            prefix_ar = "وفقاً للمستندات، "
                            prefix_en = "According to the documents, "
                        if has_arabic:
                            final_answer = (
                                f"{prefix_ar}تذكر المستندات المعلومة التالية جواباً عن سؤالك: "
                                f"{hint_for_display}"
                            )
                        else:
                            final_answer = (
                                f"{prefix_en}the documents provide the following information as the "
                                f"answer to your question: {hint_for_display}"
                            )
                    signal_value = ResponseSignal.RAG_ANSWER_SUCCESS.value if final_answer else ResponseSignal.RAG_ANSWER_ERROR.value

                    history_record = None
                    if final_answer:
                        response_time_ms = int((time.perf_counter() - start_time) * 1000)
                        history_record = await chat_history_model.create_history(
                            user_id=current_user.id,
                            conversation_id=conversation.conversation_id,
                            prompt=search_request.text,
                            answer=final_answer,
                            model_key=model_key_used,
                            doc_types=history_filter or ["all"],
                            response_time_ms=response_time_ms,
                            fallback_used=False,
                            retrieved_chunks=retrieved_chunks_count,
                            retrieved_doc_types=retrieved_doc_types or None,
                            retrieved_asset_ids=retrieved_asset_ids or None,
                            resources=answer_sources or None,
                        )
                        await conversation_model.touch_conversation(conversation.conversation_id)

                    payload = {
                        "signal": signal_value,
                        "answer": final_answer,
                        "full_prompt": full_prompt,
                        "chat_history": chat_history,
                        "conversation_id": conversation.conversation_id,
                        "conversation_title": conversation.conversation_title,
                        "document_types": history_filter or ["all"],
                        "model": model_key_used,
                        "model_id": generation_models.get(model_key_used),
                        "asset_id": asset_filter,
                        "message_id": history_record.id if history_record else None,
                        "sources": answer_sources,
                    }
                    yield json.dumps(payload) + "\n"

        return StreamingResponse(event_stream(), media_type="application/json")

    if no_answer_from_docs:
        response_time_ms = int((time.perf_counter() - start_time) * 1000)
        history_record = await chat_history_model.create_history(
            user_id=current_user.id,
            conversation_id=conversation.conversation_id,
            prompt=search_request.text,
            answer=fallback_answer,
            model_key=model_key_used,
            doc_types=history_filter or ["all"],
            response_time_ms=response_time_ms,
            fallback_used=True,
            retrieved_chunks=retrieved_chunks_count,
            retrieved_doc_types=retrieved_doc_types or None,
            retrieved_asset_ids=retrieved_asset_ids or None,
            resources=[],
        )
        await conversation_model.touch_conversation(conversation.conversation_id)

        return JSONResponse(
            content={
                "signal": ResponseSignal.RAG_ANSWER_SUCCESS.value,
                "answer": fallback_answer,
                "full_prompt": None,
                "chat_history": [],
                "conversation_id": conversation.conversation_id,
                "conversation_title": conversation.conversation_title,
                "document_types": history_filter or ["all"],
                "model": model_key_used,
                "model_id": generation_models.get(model_key_used),
                "asset_id": asset_filter,
                "message_id": history_record.id,
                "sources": [],
            }
        )

    answer = answer_result

    # For non-streaming calls, also override refusal-like answers for
    # "why / لماذا" questions when we have a direct_hint from the
    # extractor, so the user still gets a concrete, document-grounded
    # answer instead of "unknown".
    if answer and direct_hint and question_type == "why" and looks_like_refusal(answer):
        has_arabic = bool(re.search(r"[\u0600-\u06FF]", search_request.text or ""))
        hint_for_display = clean_display_hint(direct_hint)
        if doc_label_for_hint:
            prefix_ar = f'وفقاً للمستند "{doc_label_for_hint}"، '
            prefix_en = f'According to the document "{doc_label_for_hint}", '
        else:
            prefix_ar = "وفقاً للمستندات، "
            prefix_en = "According to the documents, "
        if has_arabic:
            answer = (
                f"{prefix_ar}تذكر المستندات المعلومة التالية جواباً عن سؤالك: "
                f"{hint_for_display}"
            )
        else:
            answer = (
                f"{prefix_en}the documents provide the following information as the "
                f"answer to your question: {hint_for_display}"
            )

    # Evidence-strict post-check: if there is essentially no lexical
    # overlap between the answer and the retrieved evidence, prefer the
    # standard fallback message instead of a likely hallucinated answer.
    if answer:
        tokens = re.findall(r"\w+", answer.lower(), flags=re.UNICODE)
        content_tokens = [t for t in tokens if len(t) > 3]
        # Very short answers are unlikely to be harmful; skip strict check.
        if len(content_tokens) > 3:
            unique_tokens = list(dict.fromkeys(content_tokens))
            matches = 0
            if evidence_corpus:
                for tok in unique_tokens:
                    if tok in evidence_corpus:
                        matches += 1
                        if matches >= 2:
                            break
            if not evidence_corpus or matches < 2:
                answer = fallback_answer

    if not answer:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.RAG_ANSWER_ERROR.value,
                "conversation_id": conversation.conversation_id,
                "conversation_title": conversation.conversation_title,
            }
        )

    response_time_ms = int((time.perf_counter() - start_time) * 1000)

    history_record = await chat_history_model.create_history(
        user_id=current_user.id,
        conversation_id=conversation.conversation_id,
        prompt=search_request.text,
        answer=answer,
        model_key=model_key_used,
        doc_types=history_filter or ["all"],
        response_time_ms=response_time_ms,
        fallback_used=False,
        retrieved_chunks=retrieved_chunks_count,
        retrieved_doc_types=retrieved_doc_types or None,
        retrieved_asset_ids=retrieved_asset_ids or None,
        resources=answer_sources or None,
    )
    await conversation_model.touch_conversation(conversation.conversation_id)

    return JSONResponse(
        content={
            "signal": ResponseSignal.RAG_ANSWER_SUCCESS.value,
            "answer": answer,
            "full_prompt": full_prompt,
            "chat_history": chat_history,
            "conversation_id": conversation.conversation_id,
            "conversation_title": conversation.conversation_title,
            "document_types": history_filter or ["all"],
            "model": model_key_used,
            "model_id": generation_models.get(model_key_used),
            "asset_id": asset_filter,
            "message_id": history_record.id,
            "sources": answer_sources,
        }
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
        }
    )
