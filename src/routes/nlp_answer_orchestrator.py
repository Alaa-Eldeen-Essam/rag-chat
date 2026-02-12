from fastapi import Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from typing import Any, Dict, List, Optional, Callable
from types import SimpleNamespace
import json
import logging
import math
import re
import time

from controllers import NLPController
from helpers.assets import get_asset_display_name
from helpers.config import Settings
from models import ResponseSignal
from models.AssetModel import AssetModel
from models.ChatConversationModel import ChatConversationModel
from models.ChatHistoryModel import ChatHistoryModel
from models.db_schemes import Asset, User
from models.enums.AssetTypeEnum import AssetTypeEnum
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
from routes.schemes.nlp import SearchRequest
from stores.llm.LLMEnums import DocumentTypeEnum
from stores.llm.templates.template_parser import TemplateParser
from utils.grounding import grounding_report
from utils.metrics import (
    MULTIHOP_SCOPE_PROJECTS,
    PROMPT_GUARD_BYPASS_TOTAL,
    RAG_CLARIFICATION_TOTAL,
    RAG_FALLBACK_TOTAL,
)
from utils.prompt_guard import evaluate_prompt, should_bypass_prompt_guard

logger = logging.getLogger('uvicorn.error')


async def handle_answer_rag(
    request: Request,
    project_id: int,
    search_request: SearchRequest,
    current_user: User,
    app_settings: Settings,
    language_detector: Callable[[str, str], str],
):

    # Project access check removed
    project = SimpleNamespace(project_id=project_id)

    prompt_guard_enabled = getattr(app_settings, "PROMPT_GUARD_ENABLED", True)
    pytector_enabled = getattr(app_settings, "PROMPT_GUARD_PYTECTOR", False)
    pytector_model = getattr(app_settings, "PROMPT_GUARD_PYTECTOR_MODEL", None)
    pytector_threshold = getattr(app_settings, "PROMPT_GUARD_PYTECTOR_THRESHOLD", 0.75)
    guard_bypass_header = getattr(
        app_settings, "PROMPT_GUARD_BYPASS_HEADER", "X-Bypass-Prompt-Guard"
    )
    bypass_header_value = request.headers.get(guard_bypass_header, "")
    bypass_requested = bool(
        bypass_header_value
        and bypass_header_value.strip().lower() in {"1", "true", "yes", "allow"}
    )
    bypass_allowed = should_bypass_prompt_guard(
        bypass_requested=bypass_requested,
        current_user=current_user,
    )
    if bypass_requested:
        PROMPT_GUARD_BYPASS_TOTAL.labels(
            allowed="true" if bypass_allowed else "false"
        ).inc()

    if bypass_requested and not bypass_allowed:
        logger.warning(
            "Prompt guard bypass denied for non-admin user %s",
            current_user.id,
        )

    if prompt_guard_enabled and not bypass_allowed:
        guard_result = evaluate_prompt(
            search_request.text,
            use_pytector=pytector_enabled,
            pytector_model=pytector_model,
            pytector_threshold=pytector_threshold,
        )
        if guard_result.blocked:
            detail = (
                guard_result.detail
                or "This request was blocked by the prompt guard. Please rephrase it."
            )
            logger.info(
                "Prompt guard blocked request for user %s (source=%s)",
                current_user.id,
                guard_result.source or "heuristic",
            )
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "signal": ResponseSignal.PROMPT_REJECTED.value,
                    "detail": detail,
                },
            )

    asset_label_lookup: Dict[int, str] = {}
    asset_label_lookup_by_name: Dict[str, str] = {}
    accessible_asset_ids: set[int] = set()
    assets_by_project_id: dict[int, list[Asset]] = {}
    asset_to_project: dict[int, int] = {}

    generation_clients = getattr(request.app, "generation_clients", {})
    generation_models = getattr(request.app, "generation_model_ids", {})
    default_model_key = getattr(request.app, "default_generation_model_key", None)
    default_generation_client = getattr(request.app, "generation_client", None)

    requested_model_key = (search_request.model or default_model_key or "best").lower()
    generation_client = generation_clients.get(requested_model_key) or default_generation_client
    model_key_used = requested_model_key if generation_client else default_model_key or "best"
    generation_client = generation_client or default_generation_client

    template_language = language_detector(
        search_request.text,
        app_settings.PRIMARY_LANG or app_settings.DEFAULT_LANG or "en",
    )
    template_parser = TemplateParser(
        language=template_language,
        default_language=app_settings.DEFAULT_LANG or "en",
    )

    requested_mode = (search_request.mode or "rag").strip().lower()
    if requested_mode not in {"rag", "regular", "multihop"}:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.RAG_ANSWER_ERROR.value,
                "detail": "Unsupported chat mode requested."
            }
        )
    is_regular_mode = requested_mode == "regular"
    is_multihop_mode = requested_mode == "multihop"
    history_mode_tag = f"mode:{requested_mode}"

    asset_model = None
    if not is_regular_mode:
        asset_model = await AssetModel.create_instance(
            db_client=request.app.db_client
        )
        # Collect all accessible assets across projects (own + public, or all for admins)
        all_assets = await asset_model.get_all_accessible_assets(
            asset_type=AssetTypeEnum.FILE.value,
            current_user=current_user,
        )
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

    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=template_parser,
        search_client=getattr(request.app, "search_client", None),
        reranker_client=getattr(request.app, "reranker_client", None),
        reranker_max_candidates=getattr(request.app, "reranker_max_candidates", 0),
    )
    debug_include_prompts = bool(getattr(app_settings, "DEBUG_INCLUDE_PROMPTS", False))

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
    doc_type_filter: List[str] = []
    if not is_regular_mode:
        if not explicit_doc_type or explicit_doc_type == "all":
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "signal": ResponseSignal.VECTORDB_SEARCH_ERROR.value,
                    "detail": "You must select a document type before asking questions.",
                },
            )
        doc_type_filter = [explicit_doc_type]
    asset_filter = None if is_regular_mode else search_request.asset_id
    asset_filters: Optional[List[int]] = None
    if not is_regular_mode and getattr(search_request, "asset_ids", None):
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

    def _normalize_doc_types(raw_values: Optional[List[Any]]) -> List[str]:
        values: List[str] = []
        if not raw_values:
            return values
        for value in raw_values:
            try:
                lowered = str(value).strip().lower()
            except Exception:
                continue
            if lowered:
                values.append(lowered)
        return values

    def _infer_record_mode(lowered_types: List[str]) -> Optional[str]:
        for value in lowered_types:
            if value.startswith("mode:"):
                return value.split(":", 1)[1] or None
        if lowered_types:
            return "rag"
        return None

    conversation_mode: Optional[str] = None
    for record in reversed(recent_history):
        lowered_types = _normalize_doc_types(getattr(record, "doc_types", None))
        inferred_mode = _infer_record_mode(lowered_types)
        if inferred_mode:
            conversation_mode = inferred_mode
            break

    if conversation_mode and conversation_mode != requested_mode:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.RAG_ANSWER_ERROR.value,
                "detail": "This conversation was started in a different mode. Start a new chat to switch modes.",
            },
        )

    # Build chat history for the LLM with mode-aware filtering.
    chat_messages = []
    last_user_question: Optional[str] = None
    for record in recent_history:
        lowered_types_list = _normalize_doc_types(getattr(record, "doc_types", None))
        lowered_types = set(lowered_types_list)
        record_mode = _infer_record_mode(lowered_types_list)
        if record_mode is None and is_regular_mode:
            # Treat legacy records without an explicit mode tag as RAG-only data.
            continue
        if record_mode and record_mode != requested_mode:
            continue

        if is_regular_mode:
            chat_messages.append(
                {
                    "prompt": record.prompt,
                    "answer": record.answer,
                }
            )
            if record.prompt:
                last_user_question = record.prompt
            continue

        # For RAG mode, also enforce doc_type / asset filters.
        compatible = True

        if explicit_doc_type:
            if "all" not in lowered_types and explicit_doc_type not in lowered_types:
                compatible = False

        if compatible and asset_filter is not None:
            tag = f"asset:{asset_filter}"
            if tag not in lowered_types:
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

    inferred_answer_style = nlp_controller._infer_answer_style(
        search_request.text,
        search_request.answer_style,
    )

    def _clamp_unit(value: Optional[float], default: float) -> float:
        try:
            parsed = float(value if value is not None else default)
        except (TypeError, ValueError):
            parsed = default
        return max(0.0, min(1.0, parsed))

    configured_history_weight = _clamp_unit(
        search_request.history_weight,
        getattr(app_settings, "RAG_HISTORY_WEIGHT", 0.75),
    )
    configured_ambiguity_threshold = _clamp_unit(
        search_request.ambiguity_threshold,
        getattr(app_settings, "RAG_AMBIGUITY_THRESHOLD", 0.12),
    )
    force_clarification = (
        bool(getattr(app_settings, "RAG_FORCE_CLARIFICATION", True))
        if search_request.force_clarification is None
        else bool(search_request.force_clarification)
    )

    history_max_turns = getattr(app_settings, "RAG_HISTORY_MAX_TURNS", 8)
    try:
        history_max_turns = int(history_max_turns)
    except (TypeError, ValueError):
        history_max_turns = 8
    history_max_turns = max(1, min(history_max_turns, 20))

    followup_similarity_threshold = _clamp_unit(
        getattr(app_settings, "RAG_HISTORY_FOLLOWUP_SIM_THRESHOLD", 0.30),
        0.30,
    )
    conversation_intent_context = nlp_controller.build_conversation_context(
        chat_messages=chat_messages,
        max_turns=history_max_turns,
    )

    start_time = time.perf_counter()

    if is_regular_mode:
        history_filter = [history_mode_tag]
        general_fallback = "I'm sorry, I couldn't generate a response right now."
        answer_sources: List[Dict[str, str]] = []

        answer_result, full_prompt, chat_history = await nlp_controller.generate_regular_chat_response(
            query=search_request.text,
            chat_messages=chat_messages,
            stream=bool(search_request.stream),
            collector=collector,
            answer_style=inferred_answer_style,
        )

        if search_request.stream:
            async def event_stream_regular():
                yield json.dumps({
                    "signal": ResponseSignal.RAG_ANSWER_STREAM_START.value,
                    "conversation_id": conversation.conversation_id,
                    "conversation_title": conversation.conversation_title,
                    "model": model_key_used,
                    "model_id": generation_models.get(model_key_used),
                }) + "\n"

                try:
                    if answer_result:
                        for chunk in answer_result:
                            if chunk:
                                yield json.dumps({
                                    "signal": ResponseSignal.RAG_ANSWER_STREAM_DELTA.value,
                                    "delta": chunk,
                                }) + "\n"
                finally:
                    final_answer = compose_collector_output(collector)
                    if not final_answer:
                        final_answer = general_fallback

                    response_time_ms = int((time.perf_counter() - start_time) * 1000)
                    history_record = await chat_history_model.create_history(
                        user_id=current_user.id,
                        conversation_id=conversation.conversation_id,
                        prompt=search_request.text,
                        answer=final_answer,
                        model_key=model_key_used,
                        doc_types=history_filter,
                        response_time_ms=response_time_ms,
                        fallback_used=(final_answer == general_fallback),
                        resources=answer_sources or None,
                    )
                    await conversation_model.touch_conversation(conversation.conversation_id)

                    payload = {
                        "signal": ResponseSignal.RAG_ANSWER_SUCCESS.value,
                        "answer": final_answer,
                        "full_prompt": exposed_full_prompt(
                            full_prompt,
                            debug_include_prompts=debug_include_prompts,
                        ),
                        "chat_history": exposed_chat_history(
                            chat_history,
                            debug_include_prompts=debug_include_prompts,
                        ),
                        "conversation_id": conversation.conversation_id,
                        "conversation_title": conversation.conversation_title,
                        "document_types": history_filter,
                        "model": model_key_used,
                        "model_id": generation_models.get(model_key_used),
                        "asset_id": None,
                        "message_id": history_record.id,
                        "sources": answer_sources,
                        **default_answer_metadata(),
                    }
                    yield json.dumps(payload) + "\n"

            return StreamingResponse(event_stream_regular(), media_type="application/json")

        final_answer = answer_result.strip() if isinstance(answer_result, str) else ""
        if not final_answer:
            final_answer = general_fallback

        response_time_ms = int((time.perf_counter() - start_time) * 1000)
        history_record = await chat_history_model.create_history(
            user_id=current_user.id,
            conversation_id=conversation.conversation_id,
            prompt=search_request.text,
            answer=final_answer,
            model_key=model_key_used,
            doc_types=history_filter,
            response_time_ms=response_time_ms,
            fallback_used=(final_answer == general_fallback),
            resources=answer_sources or None,
        )
        await conversation_model.touch_conversation(conversation.conversation_id)

        return JSONResponse(
            content={
                "signal": ResponseSignal.RAG_ANSWER_SUCCESS.value,
                "answer": final_answer,
                "full_prompt": exposed_full_prompt(
                    full_prompt,
                    debug_include_prompts=debug_include_prompts,
                ),
                "chat_history": exposed_chat_history(
                    chat_history,
                    debug_include_prompts=debug_include_prompts,
                ),
                "conversation_id": conversation.conversation_id,
                "conversation_title": conversation.conversation_title,
                "document_types": history_filter,
                "model": model_key_used,
                "model_id": generation_models.get(model_key_used),
                "asset_id": None,
                "message_id": history_record.id,
                "sources": answer_sources,
                **default_answer_metadata(),
            }
        )

    # Simple keyword extraction from the query for lexical re-ranking
    query_text = search_request.text or ""
    keywords = [
        w.lower()
        for w in re.findall(r"\w+", query_text, flags=re.UNICODE)
        if len(w) > 3
    ]

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

    followup_similarity: Optional[float] = None
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
                followup_similarity = _cosine_similarity(v_last, v_now)
        except Exception as exc:
            logger.error("Follow-up similarity check failed: %s", exc)

    adaptive_history_weight = nlp_controller.compute_adaptive_history_weight(
        configured_weight=configured_history_weight,
        followup_similarity=followup_similarity,
        followup_threshold=followup_similarity_threshold,
    )
    history_augmented_query = retrieval_text
    if conversation_intent_context:
        history_augmented_query = f"{conversation_intent_context}\n\n{retrieval_text}".strip()

    # Ensure requested asset filter(s) are within the user's accessible scope (RAG mode only)
    if not is_regular_mode:
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
    query_only_documents: list[Any] = []
    history_aware_documents: list[Any] = []
    search_limit = int(search_request.limit or 5)
    if asset_ids_by_project:
        if is_multihop_mode:
            MULTIHOP_SCOPE_PROJECTS.observe(float(len(asset_ids_by_project)))
        for pid, asset_ids_for_project in asset_ids_by_project.items():
            project_stub = SimpleNamespace(project_id=pid)
            query_results = await nlp_controller.search_vector_db_collection(
                project=project_stub,
                text=retrieval_text,
                limit=search_limit,
                doc_types=doc_type_filter if doc_type_filter else None,
                asset_ids=asset_ids_for_project,
                keywords=keywords or None,
            )
            if query_results:
                query_only_documents.extend(query_results)

            history_results = await nlp_controller.search_vector_db_collection(
                project=project_stub,
                text=history_augmented_query,
                limit=search_limit,
                doc_types=doc_type_filter if doc_type_filter else None,
                asset_ids=asset_ids_for_project,
                keywords=keywords or None,
            )
            if history_results:
                history_aware_documents.extend(history_results)

    retrieved_documents = nlp_controller.fuse_query_and_history_results(
        query_only_docs=query_only_documents,
        history_aware_docs=history_aware_documents,
        limit=search_limit,
        history_weight=adaptive_history_weight,
    )

    logger.debug(
        "Retrieval fusion stats: query_only=%d history_aware=%d fused=%d history_weight=%.3f sim=%s",
        len(query_only_documents),
        len(history_aware_documents),
        len(retrieved_documents),
        adaptive_history_weight,
        f"{followup_similarity:.3f}" if followup_similarity is not None else "none",
    )

    if retrieved_documents:
        retrieved_documents = await nlp_controller.rerank_documents(
            query=search_request.text or "",
            documents=retrieved_documents,
        )

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

    # For clear "when" questions where we can reliably extract a concrete
    # date from the retrieved documents, short-circuit and answer directly for
    # non-streaming calls. For "why" we prefer to pass the extracted
    # hint into the LLM so it can clean up / enrich the answer instead of
    # returning the raw snippet.
    answer_result = None
    full_prompt = None
    chat_history = None
    answer_metadata = default_answer_metadata()

    if not search_request.stream and direct_hint and question_type == "when":
        has_arabic = bool(re.search(r"[\u0600-\u06FF]", search_request.text or ""))
        if doc_label_for_hint:
            prefix_ar = f'وفقًا للمستند "{doc_label_for_hint}"، '
            prefix_en = f'According to the document "{doc_label_for_hint}", '
        else:
            prefix_ar = "وفقًا للمستندات، "
            prefix_en = "According to the documents, "

        if has_arabic:
            answer_result = f"{prefix_ar}كان ذلك في {direct_hint}."
        else:
            answer_result = f"{prefix_en}this occurred on {direct_hint}."
    else:
        if is_multihop_mode:
            # Multihop defaults
            max_hops = (
                search_request.multihop_hops
                or getattr(app_settings, "MULTIHOP_MAX_HOPS", 2)
                or 2
            )
            per_hop_k = (
                search_request.multihop_k
                or getattr(app_settings, "MULTIHOP_PER_HOP_K", 6)
                or 6
            )
            per_hop_evidence = (
                search_request.multihop_per_hop_evidence
                or getattr(app_settings, "MULTIHOP_PER_HOP_EVIDENCE", 3)
                or 3
            )
            multihop_temp = (
                search_request.multihop_temperature
                if search_request.multihop_temperature is not None
                else getattr(app_settings, "MULTIHOP_TEMPERATURE", None)
            )
            # Validate ranges before calling controller to surface friendly errors.
            if max_hops < 1 or max_hops > 5 or per_hop_k < 1 or per_hop_k > 20 or per_hop_evidence < 1:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "signal": ResponseSignal.RAG_ANSWER_ERROR.value,
                        "detail": "Invalid multihop parameters. Use hops 1-5, top_k 1-20, evidence >=1."
                    },
                )
            if per_hop_evidence > per_hop_k:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "signal": ResponseSignal.RAG_ANSWER_ERROR.value,
                        "detail": "Multihop evidence per hop must be <= top_k."
                    },
                )
            answer_result, full_prompt, chat_history, retrieved_documents, answer_metadata = await nlp_controller.generate_multihop_rag_answer(
                project=project,
                query=search_request.text,
                chat_messages=chat_messages,
                stream=bool(search_request.stream),
                collector=collector,
                doc_types=doc_type_filter,
                asset_ids=list(accessible_asset_ids) if accessible_asset_ids else None,
                max_hops=max_hops,
                per_hop_k=per_hop_k,
                per_hop_evidence=per_hop_evidence,
                generation_temperature=multihop_temp,
                answer_style=inferred_answer_style,
                conversation_context=conversation_intent_context,
                history_weight=adaptive_history_weight,
                ambiguity_threshold=configured_ambiguity_threshold,
                force_clarification=force_clarification,
                project_asset_scope=asset_ids_by_project,
            )
        else:
            answer_result, full_prompt, chat_history, answer_metadata = await nlp_controller.generate_rag_answer_from_documents(
                retrieved_documents=retrieved_documents,
                query=search_request.text,
                chat_messages=chat_messages,
                stream=bool(search_request.stream),
                collector=collector,
                asset_labels=asset_label_lookup if asset_label_lookup else None,
                asset_labels_by_name=asset_label_lookup_by_name if asset_label_lookup_by_name else None,
                direct_hint=direct_hint,
                answer_style=inferred_answer_style,
                explain_retrieval=bool(search_request.explain_retrieval),
                conversation_context=conversation_intent_context,
                ambiguity_threshold=configured_ambiguity_threshold,
                force_clarification=force_clarification,
            )

    analysis_parse_failed = bool(
        isinstance(answer_metadata, dict) and answer_metadata.get("_analysis_parse_failed", False)
    )
    analysis_source = (
        answer_metadata.get("_analysis_source")
        if isinstance(answer_metadata, dict)
        else None
    )
    answer_metadata = merged_answer_metadata(answer_metadata)
    needs_clarification = bool(answer_metadata.get("needs_clarification", False))
    if needs_clarification:
        RAG_CLARIFICATION_TOTAL.labels(mode=requested_mode).inc()

    fallback_metric_marked = False

    def mark_fallback() -> None:
        nonlocal fallback_metric_marked
        if fallback_metric_marked:
            return
        RAG_FALLBACK_TOTAL.labels(mode=requested_mode).inc()
        fallback_metric_marked = True
    metrics_snapshot = nlp_controller.record_response_metrics(
        mode=requested_mode,
        needs_clarification=needs_clarification,
        parse_failed=analysis_parse_failed,
    )
    logger.info(
        "RAG_RESPONSE_METRICS mode=%s needs_clarification=%d ambiguity_reason=%s answer_confidence=%s analysis_source=%s parse_failed=%d mode_total=%.0f mode_clarification_rate=%.3f mode_parse_failure_rate=%.3f global_total=%.0f global_clarification_rate=%.3f global_parse_failure_rate=%.3f",
        requested_mode,
        1 if needs_clarification else 0,
        str(answer_metadata.get("ambiguity_reason") or ""),
        answer_metadata.get("answer_confidence"),
        analysis_source,
        1 if analysis_parse_failed else 0,
        metrics_snapshot.get("mode_total", 0.0),
        metrics_snapshot.get("mode_clarification_rate", 0.0),
        metrics_snapshot.get("mode_parse_failure_rate", 0.0),
        metrics_snapshot.get("global_total", 0.0),
        metrics_snapshot.get("global_clarification_rate", 0.0),
        metrics_snapshot.get("global_parse_failure_rate", 0.0),
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

    answer_sources = build_answer_sources(
        retrieved_documents,
        asset_label_lookup=asset_label_lookup if asset_label_lookup else None,
    )

    history_filter = doc_type_filter.copy() if doc_type_filter else []
    if asset_filter is not None:
        history_filter.append(f"asset:{asset_filter}")
    history_filter.append(history_mode_tag)

    fallback_answer = (
        "I don't have enough information in your indexed documents to answer this question."
    )
    grounding_enabled = bool(getattr(app_settings, "RAG_GROUNDING_ENABLED", True))
    min_confidence_for_answer = _clamp_unit(
        getattr(app_settings, "RAG_MIN_ANSWER_CONFIDENCE", 0.20),
        0.20,
    )
    grounding_min_claim_overlap = _clamp_unit(
        getattr(app_settings, "RAG_GROUNDING_MIN_CLAIM_OVERLAP", 0.20),
        0.20,
    )
    grounding_max_ungrounded_claims = max(
        0,
        int(getattr(app_settings, "RAG_GROUNDING_MAX_UNGROUNDED_CLAIMS", 1) or 1),
    )
    grounding_min_token_matches = max(
        1,
        int(getattr(app_settings, "RAG_GROUNDING_MIN_TOKEN_MATCHES", 2) or 2),
    )

    def enforce_answer_safety(candidate_answer: str) -> str:
        if not candidate_answer or needs_clarification:
            return candidate_answer

        if should_fallback_for_low_confidence(
            answer_metadata,
            min_confidence=min_confidence_for_answer,
        ):
            return fallback_answer

        if not grounding_enabled:
            return candidate_answer

        report = grounding_report(
            candidate_answer,
            evidence_corpus,
            min_token_matches=grounding_min_token_matches,
            min_claim_overlap=grounding_min_claim_overlap,
            max_ungrounded_claims=grounding_max_ungrounded_claims,
        )
        if not bool(report.get("grounded", False)):
            logger.info(
                "RAG_GROUNDING_FALLBACK mode=%s lexical_matches=%s claims_checked=%s ungrounded_claims=%s avg_overlap=%.3f",
                requested_mode,
                report.get("lexical_matches"),
                report.get("claims_checked"),
                report.get("ungrounded_claims"),
                float(report.get("best_overlap_avg") or 0.0),
            )
            return fallback_answer
        return candidate_answer

    if search_request.stream:
        async def event_stream():
            # Fallback path: no answer could be produced from the documents
            if no_answer_from_docs:
                mark_fallback()
                yield json.dumps({
                    "signal": ResponseSignal.RAG_ANSWER_STREAM_START.value,
                    "conversation_id": conversation.conversation_id,
                    "conversation_title": conversation.conversation_title,
                    "model": model_key_used,
                    "model_id": generation_models.get(model_key_used),
                }) + "\n"

                yield json.dumps({
                    "signal": ResponseSignal.RAG_ANSWER_STREAM_DELTA.value,
                    "delta": fallback_answer,
                }) + "\n"

                response_time_ms = int((time.perf_counter() - start_time) * 1000)
                history_record = await chat_history_model.create_history(
                    user_id=current_user.id,
                    conversation_id=conversation.conversation_id,
                    prompt=search_request.text,
                    answer=fallback_answer,
                    model_key=model_key_used,
                    doc_types=history_filter or ["all", history_mode_tag],
                    response_time_ms=response_time_ms,
                    fallback_used=True,
                    retrieved_chunks=retrieved_chunks_count,
                    retrieved_doc_types=retrieved_doc_types or None,
                    retrieved_asset_ids=retrieved_asset_ids or None,
                    retrieved_asset_names=[
                        asset_label_lookup.get(aid)
                        for aid in (retrieved_asset_ids or [])
                        if asset_label_lookup.get(aid)
                    ] or None,
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
                    "document_types": history_filter or ["all", history_mode_tag],
                    "model": model_key_used,
                    "model_id": generation_models.get(model_key_used),
                    "asset_id": asset_filter,
                    "message_id": history_record.id,
                    "sources": [],
                    **answer_metadata,
                }
                yield json.dumps(payload) + "\n"
                return

            try:
                yield json.dumps({
                    "signal": ResponseSignal.RAG_ANSWER_STREAM_START.value,
                    "conversation_id": conversation.conversation_id,
                    "conversation_title": conversation.conversation_title,
                    "model": model_key_used,
                    "model_id": generation_models.get(model_key_used),
                }) + "\n"

                if needs_clarification:
                    clarification_text = (answer_result or answer_metadata.get("clarification_question") or "").strip()
                    if clarification_text:
                        yield json.dumps({
                            "signal": ResponseSignal.RAG_ANSWER_STREAM_DELTA.value,
                            "delta": clarification_text,
                        }) + "\n"
                else:
                    for chunk in answer_result:
                        if chunk:
                            yield json.dumps({
                                "signal": ResponseSignal.RAG_ANSWER_STREAM_DELTA.value,
                                "delta": chunk,
                            }) + "\n"
            finally:
                final_answer = compose_collector_output(collector)
                if needs_clarification:
                    final_answer = (answer_result or answer_metadata.get("clarification_question") or "").strip()

                # If we extracted a direct hint for a "why" question
                # but the model still produced a refusal-style answer, prefer
                # a deterministic answer built directly from the hint instead.
                if direct_hint and question_type == "why" and (not needs_clarification) and looks_like_refusal(final_answer):
                    has_arabic = bool(re.search(r"[\u0600-\u06FF]", search_request.text or ""))
                    hint_for_display = clean_display_hint(direct_hint)
                    if doc_label_for_hint:
                        prefix_ar = f'وفقًا للمستند "{doc_label_for_hint}"، '
                        prefix_en = f'According to the document "{doc_label_for_hint}", '
                    else:
                        prefix_ar = "وفقًا للمستندات، "
                        prefix_en = "According to the documents, "
                    if has_arabic:
                        final_answer = (
                            f"{prefix_ar}تذكر المستندات المعلومة التالية جوابًا عن سؤالك: "
                            f"{hint_for_display}"
                        )
                    else:
                        final_answer = (
                            f"{prefix_en}the documents provide the following information as the "
                            f"answer to your question: {hint_for_display}"
                        )
                final_answer = enforce_answer_safety(final_answer)
                signal_value = ResponseSignal.RAG_ANSWER_SUCCESS.value if final_answer else ResponseSignal.RAG_ANSWER_ERROR.value
                if not needs_clarification and final_answer == fallback_answer:
                    mark_fallback()

                history_record = None
                if final_answer:
                    response_time_ms = int((time.perf_counter() - start_time) * 1000)
                    history_record = await chat_history_model.create_history(
                        user_id=current_user.id,
                        conversation_id=conversation.conversation_id,
                        prompt=search_request.text,
                        answer=final_answer,
                        model_key=model_key_used,
                        doc_types=history_filter or ["all", history_mode_tag],
                        response_time_ms=response_time_ms,
                        fallback_used=(not needs_clarification and final_answer == fallback_answer),
                        retrieved_chunks=retrieved_chunks_count,
                        retrieved_doc_types=retrieved_doc_types or None,
                        retrieved_asset_ids=retrieved_asset_ids or None,
                        retrieved_asset_names=[
                            asset_label_lookup.get(aid)
                            for aid in (retrieved_asset_ids or [])
                            if asset_label_lookup.get(aid)
                        ] or None,
                        resources=answer_sources or None,
                    )
                    await conversation_model.touch_conversation(conversation.conversation_id)

                payload = {
                    "signal": signal_value,
                    "answer": final_answer,
                    "full_prompt": exposed_full_prompt(
                        full_prompt,
                        debug_include_prompts=debug_include_prompts,
                    ),
                    "chat_history": exposed_chat_history(
                        chat_history,
                        debug_include_prompts=debug_include_prompts,
                    ),
                    "conversation_id": conversation.conversation_id,
                    "conversation_title": conversation.conversation_title,
                    "document_types": history_filter or ["all", history_mode_tag],
                    "model": model_key_used,
                    "model_id": generation_models.get(model_key_used),
                    "asset_id": asset_filter,
                    "message_id": history_record.id if history_record else None,
                    "sources": answer_sources,
                    **answer_metadata,
                }
                yield json.dumps(payload) + "\n"

        return StreamingResponse(event_stream(), media_type="application/json")

    if no_answer_from_docs:
        mark_fallback()
        response_time_ms = int((time.perf_counter() - start_time) * 1000)
        history_record = await chat_history_model.create_history(
            user_id=current_user.id,
            conversation_id=conversation.conversation_id,
            prompt=search_request.text,
            answer=fallback_answer,
            model_key=model_key_used,
            doc_types=history_filter or ["all", history_mode_tag],
            response_time_ms=response_time_ms,
            fallback_used=True,
            retrieved_chunks=retrieved_chunks_count,
            retrieved_doc_types=retrieved_doc_types or None,
            retrieved_asset_ids=retrieved_asset_ids or None,
            retrieved_asset_names=[
                asset_label_lookup.get(aid)
                for aid in (retrieved_asset_ids or [])
                if asset_label_lookup.get(aid)
            ] or None,
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
                "document_types": history_filter or ["all", history_mode_tag],
                "model": model_key_used,
                "model_id": generation_models.get(model_key_used),
                "asset_id": asset_filter,
                "message_id": history_record.id,
                "sources": [],
                **answer_metadata,
            }
        )

    answer = answer_result

    # For non-streaming calls, also override refusal-like answers for
    # "why" questions when we have a direct_hint from the
    # extractor, so the user still gets a concrete, document-grounded
    # answer instead of "unknown".
    if answer and direct_hint and question_type == "why" and (not needs_clarification) and looks_like_refusal(answer):
        has_arabic = bool(re.search(r"[\u0600-\u06FF]", search_request.text or ""))
        hint_for_display = clean_display_hint(direct_hint)
        if doc_label_for_hint:
            prefix_ar = f'وفقًا للمستند "{doc_label_for_hint}"، '
            prefix_en = f'According to the document "{doc_label_for_hint}", '
        else:
            prefix_ar = "وفقًا للمستندات، "
            prefix_en = "According to the documents, "
        if has_arabic:
            answer = (
                f"{prefix_ar}تذكر المستندات المعلومة التالية جوابًا عن سؤالك: "
                f"{hint_for_display}"
            )
        else:
            answer = (
                f"{prefix_en}the documents provide the following information as the "
                f"answer to your question: {hint_for_display}"
            )

    answer = enforce_answer_safety(answer)

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
    if not needs_clarification and answer == fallback_answer:
        mark_fallback()

    history_record = await chat_history_model.create_history(
        user_id=current_user.id,
        conversation_id=conversation.conversation_id,
        prompt=search_request.text,
        answer=answer,
        model_key=model_key_used,
        doc_types=history_filter or ["all", history_mode_tag],
        response_time_ms=response_time_ms,
        fallback_used=(not needs_clarification and answer == fallback_answer),
        retrieved_chunks=retrieved_chunks_count,
        retrieved_doc_types=retrieved_doc_types or None,
        retrieved_asset_ids=retrieved_asset_ids or None,
        retrieved_asset_names=[
            asset_label_lookup.get(aid)
            for aid in (retrieved_asset_ids or [])
            if asset_label_lookup.get(aid)
        ] or None,
        resources=answer_sources or None,
    )
    await conversation_model.touch_conversation(conversation.conversation_id)

    return JSONResponse(
        content={
            "signal": ResponseSignal.RAG_ANSWER_SUCCESS.value,
            "answer": answer,
            "full_prompt": exposed_full_prompt(
                full_prompt,
                debug_include_prompts=debug_include_prompts,
            ),
            "chat_history": exposed_chat_history(
                chat_history,
                debug_include_prompts=debug_include_prompts,
            ),
            "conversation_id": conversation.conversation_id,
            "conversation_title": conversation.conversation_title,
            "document_types": history_filter or ["all", history_mode_tag],
            "model": model_key_used,
            "model_id": generation_models.get(model_key_used),
            "asset_id": asset_filter,
            "message_id": history_record.id,
            "sources": answer_sources,
            **answer_metadata,
        }
    )


