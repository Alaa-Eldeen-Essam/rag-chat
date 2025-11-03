from fastapi import FastAPI, APIRouter, status, Request
from fastapi.responses import JSONResponse
from routes.schemes.nlp import PushRequest, SearchRequest, SummarizeRequest
from models.ProjectModel import ProjectModel
from models.ChunkModel import ChunkModel
from controllers import NLPController
from models import ResponseSignal
from models.AssetModel import AssetModel

import logging

logger = logging.getLogger('uvicorn.error')

nlp_router = APIRouter(
    prefix="/api/v1/nlp",
    tags=["api_v1", "nlp"],
)

@nlp_router.post("/index/push/{project_id}")
async def index_project(request: Request, project_id: int, push_request: PushRequest):

    project_model = await ProjectModel.create_instance(
        db_client=request.app.db_client
    )

    chunk_model = await ChunkModel.create_instance(
        db_client=request.app.db_client
    )

    project = await project_model.get_project_or_create_one(
        project_id=project_id
    )

    if not project:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.PROJECT_NOT_FOUND_ERROR.value
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

    while has_records:
        page_chunks = await chunk_model.get_poject_chunks(project_id=project.project_id, page_no=page_no)
        if len(page_chunks):
            page_no += 1
        
        if not page_chunks or len(page_chunks) == 0:
            has_records = False
            break

        chunks_ids =  list(range(idx, idx + len(page_chunks)))
        idx += len(page_chunks)
        
        is_inserted = nlp_controller.index_into_vector_db(
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
        
        inserted_items_count += len(page_chunks)
        
    return JSONResponse(
        content={
            "signal": ResponseSignal.INSERT_INTO_VECTORDB_SUCCESS.value,
            "inserted_items_count": inserted_items_count
        }
    )

@nlp_router.get("/index/info/{project_id}")
async def get_project_index_info(request: Request, project_id: int):
    
    project_model = await ProjectModel.create_instance(
        db_client=request.app.db_client
    )

    project = await project_model.get_project_or_create_one(
        project_id=project_id
    )

    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=request.app.generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=request.app.template_parser,
    )

    collection_info = nlp_controller.get_vector_db_collection_info(project=project)

    return JSONResponse(
        content={
            "signal": ResponseSignal.VECTORDB_COLLECTION_RETRIEVED.value,
            "collection_info": collection_info
        }
    )

@nlp_router.post("/index/search/{project_id}")
async def search_index(request: Request, project_id: int, search_request: SearchRequest):
    
    project_model = await ProjectModel.create_instance(
        db_client=request.app.db_client
    )

    project = await project_model.get_project_or_create_one(
        project_id=project_id
    )

    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=request.app.generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=request.app.template_parser,
    )

    results = nlp_controller.search_vector_db_collection(
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
async def answer_rag(request: Request, project_id: int, search_request: SearchRequest):
    
    project_model = await ProjectModel.create_instance(
        db_client=request.app.db_client
    )

    project = await project_model.get_project_or_create_one(
        project_id=project_id
    )

    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=request.app.generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=request.app.template_parser,
    )

    answer, full_prompt, chat_history = nlp_controller.answer_rag_question(
        project=project,
        query=search_request.text,
        limit=search_request.limit,
    )

    if not answer:
        return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "signal": ResponseSignal.RAG_ANSWER_ERROR.value
                }
        )
    
    return JSONResponse(
        content={
            "signal": ResponseSignal.RAG_ANSWER_SUCCESS.value,
            "answer": answer,
            "full_prompt": full_prompt,
            "chat_history": chat_history
        }
    )

@nlp_router.post("/summary/{project_id}")
async def summarize_project(request: Request, project_id: int, summarize_request: SummarizeRequest):

    project_model = await ProjectModel.create_instance(
        db_client=request.app.db_client
    )

    chunk_model = await ChunkModel.create_instance(
        db_client=request.app.db_client
    )

    asset_model = await AssetModel.create_instance(
        db_client=request.app.db_client
    )

    project = await project_model.get_project_or_create_one(
        project_id=project_id
    )

    target_asset_id = None
    selected_file = None

    if summarize_request.file_id:
        asset_record = await asset_model.get_asset_record(
            asset_project_id=project.project_id,
            asset_name=summarize_request.file_id
        )

        if asset_record is None:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "signal": ResponseSignal.FILE_ID_ERROR.value,
                    "detail": "No file found with the provided file identifier."
                }
            )

        target_asset_id = asset_record.asset_id
        selected_file = asset_record.asset_name

    max_chunks = None
    if summarize_request.max_chunks and summarize_request.max_chunks > 0:
        max_chunks = summarize_request.max_chunks

    chunks = await chunk_model.get_project_chunks_for_summary(
        project_id=project.project_id,
        asset_id=target_asset_id,
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
        max_output_tokens=summarize_request.max_output_tokens
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
