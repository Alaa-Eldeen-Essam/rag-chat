from fastapi import APIRouter, status, Request, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from routes.schemes.nlp import PushRequest, SearchRequest, SummarizeRequest
from models.ProjectModel import ProjectModel
from models.ChunkModel import ChunkModel
from controllers import NLPController
from models import ResponseSignal
from models.AssetModel import AssetModel
from models.ChatHistoryModel import ChatHistoryModel, MAX_CONVERSATION_MESSAGES
from models.ChatConversationModel import ChatConversationModel
from models.db_schemes import User, Asset
from routes.dependencies import get_current_user
from helpers.assets import get_asset_display_name
from models.enums.AssetTypeEnum import AssetTypeEnum
from sqlalchemy import select
from tqdm.auto import tqdm

import logging
import json
import time
from typing import List, Optional

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

    project_model = await ProjectModel.create_instance(
        db_client=request.app.db_client
    )

    chunk_model = await ChunkModel.create_instance(
        db_client=request.app.db_client
    )

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
    
    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=request.app.generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=request.app.template_parser,
    )

    has_records = True
    page_no = 1
    inserted_items_count = 0
    idx = 0
    # create collection if not exists
    collection_name = nlp_controller.create_collection_name(project_id=project.project_id)

    _ = await request.app.vectordb_client.create_collection(
        collection_name=collection_name,
        embedding_size=request.app.embedding_client.embedding_size,
        do_reset=push_request.do_reset,
    )

    # setup batching
    total_chunks_count = await chunk_model.get_total_chunks_count(project_id=project.project_id)
    pbar = tqdm(total=total_chunks_count, desc="Vector Indexing", position=0)

    while has_records:
        page_chunks = await chunk_model.get_poject_chunks(project_id=project.project_id, page_no=page_no)
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
            do_reset=push_request.do_reset,
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
            "conversations": payload
        }
    )

@nlp_router.get("/doc-types")
async def list_user_doc_types(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    async with request.app.db_client() as session:
        result = await session.execute(
            select(Asset.asset_document_type)
            .where(
                Asset.asset_user_id == current_user.id,
                Asset.asset_document_type.isnot(None)
            )
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
            "doc_types": doc_types
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

    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=request.app.generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=request.app.template_parser,
    )

    results = await nlp_controller.search_vector_db_collection(
        project=project, text=search_request.text, limit=search_request.limit
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
    asset_label_lookup = {}
    asset_label_lookup_by_name = {}
    for asset in project_assets:
        display_name = get_asset_display_name(asset) or asset.asset_name
        asset_label_lookup[asset.asset_id] = display_name
        asset_label_lookup_by_name[asset.asset_name] = display_name

    generation_clients = getattr(request.app, "generation_clients", {})
    generation_models = getattr(request.app, "generation_model_ids", {})
    default_model_key = getattr(request.app, "default_generation_model_key", None)
    default_generation_client = getattr(request.app, "generation_client", None)

    requested_model_key = (search_request.model or default_model_key or "best").lower()
    generation_client = generation_clients.get(requested_model_key) or default_generation_client
    model_key_used = requested_model_key if generation_client else default_model_key or "best"
    generation_client = generation_client or default_generation_client

    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=request.app.template_parser,
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

    recent_history = await chat_history_model.get_recent_history_by_conversation(
        conversation_id=conversation.conversation_id,
        limit=5
    )

    chat_messages = [
        {
            "prompt": record.prompt,
            "answer": record.answer,
        }
        for record in recent_history
    ]

    collector = {"output": [], "reasoning": []} if search_request.stream else None
    doc_type_filter = extract_document_types_from_query(search_request.text)
    asset_filter = search_request.asset_id
    start_time = time.perf_counter()

    answer_result, full_prompt, chat_history = await nlp_controller.answer_rag_question(
        project=project,
        query=search_request.text,
        limit=search_request.limit,
        chat_messages=chat_messages,
        stream=bool(search_request.stream),
        collector=collector,
        doc_types=doc_type_filter if doc_type_filter else None,
        asset_ids=[asset_filter] if asset_filter else None,
        asset_labels=asset_label_lookup if asset_label_lookup else None,
        asset_labels_by_name=asset_label_lookup_by_name if asset_label_lookup_by_name else None,
    )

    if full_prompt is None or chat_history is None:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.RAG_ANSWER_ERROR.value,
                "conversation_id": conversation.conversation_id,
                "conversation_title": conversation.conversation_title,
            }
        )

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

    if search_request.stream:
        if answer_result is None:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "signal": ResponseSignal.RAG_ANSWER_ERROR.value
                }
            )

        async def event_stream():
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
                signal_value = ResponseSignal.RAG_ANSWER_SUCCESS.value if final_answer else ResponseSignal.RAG_ANSWER_ERROR.value

                if final_answer:
                    response_time_ms = int((time.perf_counter() - start_time) * 1000)
                    await chat_history_model.create_history(
                        user_id=current_user.id,
                        conversation_id=conversation.conversation_id,
                        prompt=search_request.text,
                        answer=final_answer,
                        model_key=model_key_used,
                        doc_types=doc_type_filter or ["all"],
                        response_time_ms=response_time_ms,
                    )
                    await conversation_model.touch_conversation(conversation.conversation_id)

                history_filter = doc_type_filter.copy() if doc_type_filter else []
                if asset_filter is not None:
                    history_filter.append(f"asset:{asset_filter}")

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
                }
                yield json.dumps(payload) + "\n"

        return StreamingResponse(event_stream(), media_type="application/json")

    answer = answer_result

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

    history_filter = doc_type_filter.copy() if doc_type_filter else []
    if asset_filter is not None:
        history_filter.append(f"asset:{asset_filter}")

    await chat_history_model.create_history(
        user_id=current_user.id,
        conversation_id=conversation.conversation_id,
        prompt=search_request.text,
        answer=answer,
        model_key=model_key_used,
        doc_types=history_filter or ["all"],
        response_time_ms=response_time_ms,
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
        }
    )

@nlp_router.post("/summary/{project_id}")
async def summarize_project(
    request: Request,
    project_id: int,
    summarize_request: SummarizeRequest,
    current_user: User = Depends(get_current_user),
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

    chunks = await chunk_model.get_project_chunks_for_summary(
        project_id=project.project_id,
        asset_ids=accessible_asset_ids,
        limit=max_chunks
    )

    if not chunks:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.SUMMARY_GENERATION_ERROR.value,
                "detail": "No processed chunks found for summarization. Ensure the project data is processed first."
            }
        )

    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=request.app.generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=request.app.template_parser,
    )

    summary, full_prompt = nlp_controller.summarize_chunks(
        chunks=chunks,
        focus=summarize_request.focus,
        max_output_tokens=summarize_request.max_output_tokens,
        asset_labels=asset_label_lookup if asset_label_lookup else None,
        asset_labels_by_name=asset_label_lookup_by_name if asset_label_lookup_by_name else None,
    )

    if not summary:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.SUMMARY_GENERATION_ERROR.value,
                "detail": "The summarization provider did not return any content."
            }
        )

    return JSONResponse(
        content={
            "signal": ResponseSignal.SUMMARY_GENERATION_SUCCESS.value,
            "summary": summary,
            "used_chunks": len(chunks),
            "file_id": selected_file,
            "focus": summarize_request.focus,
            "max_output_tokens": summarize_request.max_output_tokens,
            "full_prompt": full_prompt,
        }
    )
