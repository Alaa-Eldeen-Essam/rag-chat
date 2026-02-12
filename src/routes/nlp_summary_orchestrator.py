from fastapi import Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from types import SimpleNamespace
from typing import Any, Callable, Dict, List
import json

from controllers import NLPController
from helpers.assets import get_asset_display_name
from helpers.config import Settings
from models import ResponseSignal
from models.AssetModel import AssetModel
from models.ChunkModel import ChunkModel
from models.SummaryModel import SummaryModel
from models.db_schemes import Asset, SummaryRecord, User
from models.enums.AssetTypeEnum import AssetTypeEnum
from routes.schemes.nlp import DeleteSummariesRequest, SummarizeRequest
from stores.llm.templates.template_parser import TemplateParser


async def handle_summarize_project(
    request: Request,
    project_id: int,
    summarize_request: SummarizeRequest,
    current_user: User,
    app_settings: Settings,
    language_detector: Callable[[str, str], str],
):
    from models.ProjectModel import ProjectModel

    project_model = await ProjectModel.create_instance(db_client=request.app.db_client)
    chunk_model = await ChunkModel.create_instance(db_client=request.app.db_client)
    asset_model = await AssetModel.create_instance(db_client=request.app.db_client)

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
                "detail": f"Unknown model '{summarize_request.model}'.",
            },
        )

    generation_client = selected_generation_client or default_generation_client
    if generation_client is None:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "signal": ResponseSignal.RAG_ANSWER_ERROR.value,
                "detail": "Generation backend is not configured.",
            },
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
        response_status = (
            status.HTTP_403_FORBIDDEN if status_code == "forbidden" else status.HTTP_404_NOT_FOUND
        )
        response_signal = (
            ResponseSignal.ACCESS_FORBIDDEN_ERROR.value
            if status_code == "forbidden"
            else ResponseSignal.PROJECT_NOT_FOUND_ERROR.value
        )
        return JSONResponse(status_code=response_status, content={"signal": response_signal})

    target_asset_id = None
    selected_file = None
    accessible_asset_ids: List[int] = []
    asset_label_lookup: Dict[int, str] = {}
    asset_label_lookup_by_name: Dict[str, str] = {}

    if summarize_request.file_id:
        asset_record, record_exists = await asset_model.get_asset_record(
            asset_project_id=project.project_id,
            asset_name=summarize_request.file_id,
            current_user=current_user,
        )

        if asset_record is None:
            signal = (
                ResponseSignal.ACCESS_FORBIDDEN_ERROR.value
                if record_exists
                else ResponseSignal.FILE_ID_ERROR.value
            )
            status_code_response = (
                status.HTTP_403_FORBIDDEN if record_exists else status.HTTP_400_BAD_REQUEST
            )
            detail = (
                "File is private to another user."
                if record_exists
                else "No file found with the provided file identifier."
            )
            return JSONResponse(
                status_code=status_code_response,
                content={"signal": signal, "detail": detail},
            )

        target_asset_id = asset_record.asset_id
        selected_file = asset_record.asset_name
        accessible_asset_ids = [asset_record.asset_id]
        display_name = get_asset_display_name(asset_record) or asset_record.asset_name
        asset_label_lookup[asset_record.asset_id] = display_name
        asset_label_lookup_by_name[asset_record.asset_name] = display_name

    if target_asset_id is None:
        project_assets = await asset_model.get_all_project_assets(
            asset_project_id=project.project_id,
            asset_type=AssetTypeEnum.FILE.value,
            current_user=current_user,
        )
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
                "detail": "No accessible files are available for summarization.",
            },
        )

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
                "detail": "No processed chunks found for summarization. Ensure the project data is processed first.",
            },
        )

    total_chunks = len(chunks)
    focus_text = (summarize_request.focus or "").strip()
    if focus_text and total_chunks > 100:
        keywords = [word.lower() for word in focus_text.split() if len(word) > 3]
        if keywords:
            filtered_chunks = [
                chunk
                for chunk in chunks
                if any(kw in (getattr(chunk, "chunk_text", "") or "").lower() for kw in keywords)
            ]
            if len(filtered_chunks) >= 10:
                chunks = filtered_chunks
                total_chunks = len(chunks)

    source_chunks = chunks

    summary_max_tokens = (
        summarize_request.max_output_tokens
        or app_settings.SUMMARY_DEFAULT_MAX_TOKENS
        or app_settings.GENERATION_DAFAULT_MAX_TOKENS
    )

    sample_text_parts: List[str] = []
    for chunk in source_chunks[:3]:
        chunk_text = getattr(chunk, "chunk_text", "") or ""
        if chunk_text:
            sample_text_parts.append(chunk_text)
    sample_text = " ".join(sample_text_parts)[:2000] if sample_text_parts else ""

    template_language = language_detector(
        sample_text,
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

    summary_input_chunks = chunks
    hierarchical_threshold = 120
    section_size = 10
    max_section_summaries = 20

    if total_chunks > hierarchical_threshold:
        section_summaries: List[str] = []
        section_max_tokens = min(summary_max_tokens, 256)

        for i in range(0, total_chunks, section_size):
            section = chunks[i : i + section_size]
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
            if len(section_summaries) > max_section_summaries:
                step = len(section_summaries) / max_section_summaries
                selected: List[str] = []
                for idx in range(max_section_summaries):
                    pos = int(idx * step)
                    if pos >= len(section_summaries):
                        pos = len(section_summaries) - 1
                    selected.append(section_summaries[pos])
                section_summaries = selected

            summary_input_chunks = [
                SimpleNamespace(
                    chunk_text=text,
                    chunk_order=idx + 1,
                    chunk_metadata={"section_index": idx + 1},
                )
                for idx, text in enumerate(section_summaries)
            ]

    summary_model = await SummaryModel.create_instance(db_client=request.app.db_client)

    chunk_ids = [
        chunk.chunk_id
        for chunk in source_chunks
        if getattr(chunk, "chunk_id", None) is not None
    ]

    stream_enabled = summarize_request.stream if summarize_request.stream is not None else True
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
                yield json.dumps(
                    {
                        "signal": ResponseSignal.SUMMARY_STREAM_START.value,
                        "file_id": selected_file,
                        "focus": summarize_request.focus,
                        "max_output_tokens": summary_max_tokens,
                        "used_chunks": len(chunks),
                        "model": model_key_used,
                        "model_id": model_id_used,
                    }
                ) + "\n"

                for chunk in summary_output:
                    if chunk:
                        yield json.dumps(
                            {
                                "signal": ResponseSignal.SUMMARY_STREAM_DELTA.value,
                                "delta": chunk,
                            }
                        ) + "\n"
            finally:
                final_summary = "".join(collector.get("output", [])) if collector else ""
                final_summary = final_summary.strip()
                signal_value = (
                    ResponseSignal.SUMMARY_GENERATION_SUCCESS.value
                    if final_summary
                    else ResponseSignal.SUMMARY_GENERATION_ERROR.value
                )

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
                "detail": "The summarization provider did not return any content.",
            },
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


async def handle_list_summaries(
    request: Request,
    limit: int,
    current_user: User,
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

    summaries: List[Dict[str, Any]] = []
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
                "created_at": (
                    summary_record.created_at.isoformat() if summary_record.created_at else None
                ),
            }
        )

    return JSONResponse(content={"summaries": summaries, "total": len(summaries)})


async def handle_get_summary(
    request: Request,
    summary_id: int,
    current_user: User,
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
            "created_at": (
                summary_record.created_at.isoformat() if summary_record.created_at else None
            ),
            "prompt_text": summary_record.prompt_text,
            "max_output_tokens_used": summary_record.max_output_tokens,
        }
    )


async def handle_delete_summary(
    request: Request,
    summary_id: int,
    current_user: User,
):
    summary_model = await SummaryModel.create_instance(db_client=request.app.db_client)
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


async def handle_delete_summaries_bulk(
    request: Request,
    payload: DeleteSummariesRequest,
    current_user: User,
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

    summary_model = await SummaryModel.create_instance(db_client=request.app.db_client)

    deleted_ids: List[int] = []
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
