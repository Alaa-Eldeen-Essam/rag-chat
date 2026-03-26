from fastapi import Request, status
from fastapi.responses import JSONResponse
from typing import List
import logging
import re

from controllers import NLPController
from helpers.config import get_settings
from models import ResponseSignal
from models.AssetModel import AssetModel
from models.ChunkModel import ChunkModel
from models.ProjectModel import ProjectModel
from models.db_schemes import User
from models.enums.AssetTypeEnum import AssetTypeEnum
from routes.schemes.nlp import PushRequest, SearchRequest
from stores.llm.templates.template_parser import TemplateParser

logger = logging.getLogger(__name__)


async def handle_index_project(
    request: Request,
    project_id: int,
    push_request: PushRequest,
    current_user: User,
):
    app_settings = get_settings()
    generation_client = getattr(request.app, "generation_client", None)

    project_model = await ProjectModel.create_instance(db_client=request.app.db_client)
    chunk_model = await ChunkModel.create_instance(db_client=request.app.db_client)
    asset_model = await AssetModel.create_instance(db_client=request.app.db_client)
    target_asset_id = None

    project, status_code = await project_model.get_project_or_create_one(
        project_id=project_id,
        current_user=current_user,
        create_if_missing=False,
        is_private=None,
        require_owner=True,
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

    if push_request.asset_name:
        asset_record, record_exists = await asset_model.get_asset_record(
            asset_project_id=project.project_id,
            asset_name=push_request.asset_name,
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
    collection_name = nlp_controller.create_collection_name(project_id=project.project_id)

    do_reset_flag = bool(push_request.do_reset)
    _ = await request.app.vectordb_client.create_collection(
        collection_name=collection_name,
        embedding_size=request.app.embedding_client.embedding_size,
        do_reset=do_reset_flag,
    )
    do_reset_flag = False

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

    while has_records:
        page_chunks = await chunk_model.get_poject_chunks(
            project_id=project.project_id,
            page_no=page_no,
            asset_id=target_asset_id,
        )
        if len(page_chunks):
            page_no += 1

        if not page_chunks:
            has_records = False
            break

        chunks_ids = [c.chunk_id for c in page_chunks]
        is_inserted = await nlp_controller.index_into_vector_db(
            project=project,
            chunks=page_chunks,
            do_reset=do_reset_flag,
            chunks_ids=chunks_ids,
        )

        if not is_inserted:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"signal": ResponseSignal.INSERT_INTO_VECTORDB_ERROR.value},
            )

        inserted_items_count += len(page_chunks)
        logger.info(
            "INDEX_PROGRESS project_id=%s inserted=%d total=%d",
            project.project_id,
            inserted_items_count,
            total_chunks_count,
        )

    return JSONResponse(
        content={
            "signal": ResponseSignal.INSERT_INTO_VECTORDB_SUCCESS.value,
            "inserted_items_count": inserted_items_count,
        }
    )


async def handle_get_project_index_info(
    request: Request,
    project_id: int,
    current_user: User,
):
    project_model = await ProjectModel.create_instance(db_client=request.app.db_client)

    project, status_code = await project_model.get_project_or_create_one(
        project_id=project_id,
        current_user=current_user,
        create_if_missing=True,
        is_private=None,
        require_owner=False,
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

    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=request.app.generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=request.app.template_parser,
        search_client=getattr(request.app, "search_client", None),
        reranker_client=getattr(request.app, "reranker_client", None),
        reranker_max_candidates=getattr(request.app, "reranker_max_candidates", 0),
    )

    collection_info = await nlp_controller.get_vector_db_collection_info(project=project)
    return JSONResponse(
        content={
            "signal": ResponseSignal.VECTORDB_COLLECTION_RETRIEVED.value,
            "collection_info": collection_info,
        }
    )


async def handle_search_index(
    request: Request,
    project_id: int,
    search_request: SearchRequest,
    current_user: User,
):
    project_model = await ProjectModel.create_instance(db_client=request.app.db_client)

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

    asset_model = await AssetModel.create_instance(db_client=request.app.db_client)
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
                "detail": "No accessible files are available for search in this project.",
            },
        )

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

    query_text = search_request.text or ""
    keywords: List[str] = [
        w.lower() for w in re.findall(r"\w+", query_text, flags=re.UNICODE) if len(w) > 3
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
            content={"signal": ResponseSignal.VECTORDB_SEARCH_ERROR.value},
        )

    return JSONResponse(
        content={
            "signal": ResponseSignal.VECTORDB_SEARCH_SUCCESS.value,
            "results": [result.dict() for result in results],
        }
    )
