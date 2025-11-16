from fastapi import APIRouter, Depends, UploadFile, status, Request, Form, Query, File
from fastapi.responses import JSONResponse
import os
from helpers.config import get_settings, Settings
from helpers.assets import get_asset_display_name
from controllers import DataController, ProjectController, ProcessController, NLPController
import aiofiles
from models import ResponseSignal
import logging
from .schemes.data import ProcessRequest
from models.ProjectModel import ProjectModel
from models.ChunkModel import ChunkModel
from models.AssetModel import AssetModel
from models.db_schemes import DataChunk, Asset, User
from models.enums.AssetTypeEnum import AssetTypeEnum
from routes.dependencies import get_current_user
from typing import List, Optional

logger = logging.getLogger('uvicorn.error')

data_router = APIRouter(
    prefix="/api/v1/data",
    tags=["api_v1", "data"],
)

DOCUMENT_TYPE_DEFAULT = "general"


def normalize_document_type(value: str) -> str:
    if not value:
        return DOCUMENT_TYPE_DEFAULT
    normalized = value.strip()
    return normalized if normalized else DOCUMENT_TYPE_DEFAULT

@data_router.post("/upload/{project_id}")
async def upload_data(
    request: Request,
    project_id: int,
    file: UploadFile,
    is_private: bool = Form(True),
    doc_type: str = Form(DOCUMENT_TYPE_DEFAULT),
    visibility: str = Form("private"),
    department: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    app_settings: Settings = Depends(get_settings),
):
    project_model = await ProjectModel.create_instance(
        db_client=request.app.db_client
    )

    project, status_code = await project_model.get_project_or_create_one(
        project_id=project_id,
        current_user=current_user,
        create_if_missing=True,
        is_private=is_private,
        require_owner=True,
    )

    if project is None:
        response_status = status.HTTP_403_FORBIDDEN if status_code == "forbidden" else status.HTTP_404_NOT_FOUND
        response_signal = ResponseSignal.ACCESS_FORBIDDEN_ERROR.value if status_code == "forbidden" else ResponseSignal.PROJECT_NOT_FOUND_ERROR.value
        return JSONResponse(
            status_code=response_status,
            content={
                "signal": response_signal
            }
        )

    data_controller = DataController()

    is_valid, result_signal = data_controller.validate_uploaded_file(file=file)

    if not is_valid:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": result_signal
            }
        )

    project_dir_path = ProjectController().get_project_path(project_id=project_id)
    file_path, file_id = data_controller.generate_unique_filepath(
        orig_file_name=file.filename,
        project_id=project_id
    )

    try:
        async with aiofiles.open(file_path, "wb") as f:
            while chunk := await file.read(app_settings.FILE_DEFAULT_CHUNK_SIZE):
                await f.write(chunk)
    except Exception as e:

        logger.error(f"Error while uploading file: {e}")

        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.FILE_UPLOAD_FAILED.value
            }
        )

    asset_model = await AssetModel.create_instance(
        db_client=request.app.db_client
    )

    vis = (visibility or "").strip().lower()
    if vis not in ("private", "department", "global"):
        vis = "private" if is_private else "global"
    effective_department = None
    if vis == "department":
        effective_department = (department or getattr(current_user, "department", None) or "Global")

    normalized_doc_type = normalize_document_type(doc_type)

    asset_resource = Asset(
        asset_project_id=project.project_id,
        asset_user_id=current_user.id,
        asset_type=AssetTypeEnum.FILE.value,
        asset_name=file_id,
        asset_size=os.path.getsize(file_path),
        asset_is_private=(vis == "private"),
        asset_visibility=vis,
        asset_department=effective_department,
        asset_document_type=normalized_doc_type,
        asset_config={
            "original_filename": file.filename
        },
    )

    asset_record = await asset_model.create_asset(asset=asset_resource)

    return JSONResponse(
            content={
                "signal": ResponseSignal.FILE_UPLOAD_SUCCESS.value,
                "file_id": str(asset_record.asset_id),
                "stored_file_name": asset_record.asset_name,
                "original_file_name": file.filename,
                "is_private": asset_record.asset_is_private,
                "doc_type": asset_record.asset_document_type,
            }
        )

@data_router.post("/upload/process/index/{project_id}")
async def upload_process_index(
    request: Request,
    project_id: int,
    file: UploadFile,
    chunk_size: int = Form(1200),
    overlap_size: int = Form(250),
    do_reset: int = Form(0),
    is_private: bool = Form(True),
    doc_type: str = Form(DOCUMENT_TYPE_DEFAULT),
    visibility: str = Form("private"),
    department: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    app_settings: Settings = Depends(get_settings),
):

    project_model = await ProjectModel.create_instance(
        db_client=request.app.db_client
    )

    project, status_code = await project_model.get_project_or_create_one(
        project_id=project_id,
        current_user=current_user,
        create_if_missing=True,
        is_private=is_private,
        require_owner=False,
    )

    if project is None:
        response_status = status.HTTP_403_FORBIDDEN if status_code == "forbidden" else status.HTTP_404_NOT_FOUND
        response_signal = ResponseSignal.ACCESS_FORBIDDEN_ERROR.value if status_code == "forbidden" else ResponseSignal.PROJECT_NOT_FOUND_ERROR.value
        return JSONResponse(
            status_code=response_status,
            content={
                "signal": response_signal
            }
        )

    data_controller = DataController()
    is_valid, result_signal = data_controller.validate_uploaded_file(file=file)

    if not is_valid:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": result_signal
            }
        )

    _ = ProjectController().get_project_path(project_id=project_id)
    file_path, file_id = data_controller.generate_unique_filepath(
        orig_file_name=file.filename,
        project_id=project_id
    )

    try:
        async with aiofiles.open(file_path, "wb") as f:
            while chunk := await file.read(app_settings.FILE_DEFAULT_CHUNK_SIZE):
                await f.write(chunk)
    except Exception as exc:
        logger.error("Error while uploading file: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.FILE_UPLOAD_FAILED.value
            }
        )

    asset_model = await AssetModel.create_instance(
        db_client=request.app.db_client
    )
    chunk_model = await ChunkModel.create_instance(
        db_client=request.app.db_client
    )

    vis = (visibility or "").strip().lower()
    if vis not in ("private", "department", "global"):
        vis = "private" if is_private else "global"
    effective_department = None
    if vis == "department":
        effective_department = (department or getattr(current_user, "department", None) or "Global")

    normalized_doc_type = normalize_document_type(doc_type)
    asset_resource = Asset(
        asset_project_id=project.project_id,
        asset_user_id=current_user.id,
        asset_type=AssetTypeEnum.FILE.value,
        asset_name=file_id,
        asset_size=os.path.getsize(file_path),
        asset_is_private=(vis == "private"),
        asset_visibility=vis,
        asset_department=effective_department,
        asset_document_type=normalized_doc_type,
        asset_config={
            "original_filename": file.filename
        },
    )
    asset_record = await asset_model.create_asset(asset=asset_resource)

    process_controller = ProcessController(project_id=project_id)
    file_content = process_controller.get_file_content(file_id=file_id)

    if file_content is None:
        logger.error("Error while processing uploaded file: %s", file_id)
        await asset_model.delete_asset(asset_record)
        if os.path.exists(file_path):
            os.remove(file_path)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.PROCESSING_FAILED.value
            }
        )

    file_chunks = process_controller.process_file_content(
        file_content=file_content,
        file_id=file_id,
        chunk_size=chunk_size,
        overlap_size=overlap_size
    )

    if not file_chunks:
        await asset_model.delete_asset(asset_record)
        if os.path.exists(file_path):
            os.remove(file_path)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.PROCESSING_FAILED.value
            }
        )

    existing_chunk_ids = set(await chunk_model.get_chunk_ids_by_asset_ids([asset_record.asset_id]))

    file_chunks_records = [
        DataChunk(
            chunk_text=chunk.page_content,
            chunk_metadata={
                **(chunk.metadata or {}),
                "doc_type": normalized_doc_type,
                "asset_id": asset_record.asset_id,
                "source_name": file.filename,
                "original_filename": file.filename,
            },
            chunk_order=i + 1,
            chunk_project_id=project.project_id,
            chunk_asset_id=asset_record.asset_id,
        )
        for i, chunk in enumerate(file_chunks)
    ]

    await chunk_model.insert_many_chunks(file_chunks_records)

    updated_chunk_ids = set(await chunk_model.get_chunk_ids_by_asset_ids([asset_record.asset_id]))
    new_chunk_ids = sorted(updated_chunk_ids - existing_chunk_ids)
    new_chunks = await chunk_model.get_chunks_by_ids(new_chunk_ids)

    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=request.app.generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=request.app.template_parser,
    )

    indexed = await nlp_controller.index_into_vector_db(
        project=project,
        chunks=new_chunks,
        chunks_ids=new_chunk_ids,
        do_reset=bool(do_reset),
    )

    if not indexed:
        await chunk_model.delete_chunks_by_asset_ids([asset_record.asset_id])
        await asset_model.delete_asset(asset_record)
        await request.app.vectordb_client.delete_records(
            nlp_controller.create_collection_name(project.project_id),
            new_chunk_ids,
        )
        if os.path.exists(file_path):
            os.remove(file_path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "signal": ResponseSignal.INSERT_INTO_VECTORDB_ERROR.value,
                "detail": "Failed to index chunks into the vector database.",
            },
        )

    return JSONResponse(
        content={
            "signal": ResponseSignal.INSERT_INTO_VECTORDB_SUCCESS.value,
            "asset_id": asset_record.asset_id,
            "stored_file_name": asset_record.asset_name,
            "original_file_name": file.filename,
            "chunks_created": len(new_chunk_ids),
            "indexed_chunks": len(new_chunk_ids),
            "collection_name": nlp_controller.create_collection_name(project.project_id),
        }
    )


@data_router.post("/upload/process/index/batch/{project_id}")
async def upload_process_index_batch(
    request: Request,
    project_id: int,
    files: List[UploadFile] = File(...),
    chunk_size: int = Form(1200),
    overlap_size: int = Form(250),
    do_reset: int = Form(0),
    is_private: bool = Form(True),
    doc_type: str = Form(DOCUMENT_TYPE_DEFAULT),
    visibility: str = Form("private"),
    department: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    app_settings: Settings = Depends(get_settings),
):
    if not files:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.FILE_UPLOAD_FAILED.value,
                "detail": "No files provided for upload."
            }
        )

    project_model = await ProjectModel.create_instance(
        db_client=request.app.db_client
    )

    project, status_code = await project_model.get_project_or_create_one(
        project_id=project_id,
        current_user=current_user,
        create_if_missing=True,
        is_private=is_private,
        require_owner=False,
    )

    if project is None:
        response_status = status.HTTP_403_FORBIDDEN if status_code == "forbidden" else status.HTTP_404_NOT_FOUND
        response_signal = ResponseSignal.ACCESS_FORBIDDEN_ERROR.value if status_code == "forbidden" else ResponseSignal.PROJECT_NOT_FOUND_ERROR.value
        return JSONResponse(
            status_code=response_status,
            content={
                "signal": response_signal
            }
        )

    data_controller = DataController()
    asset_model = await AssetModel.create_instance(
        db_client=request.app.db_client
    )
    chunk_model = await ChunkModel.create_instance(
        db_client=request.app.db_client
    )

    vis = (visibility or "").strip().lower()
    if vis not in ("private", "department", "global"):
        vis = "private" if is_private else "global"
    effective_department = None
    if vis == "department":
        effective_department = (
            department or getattr(current_user, "department", None) or "Global"
        )

    normalized_doc_type = normalize_document_type(doc_type)

    results = []

    for upload_file in files:
        is_valid, result_signal = data_controller.validate_uploaded_file(
            file=upload_file
        )
        if not is_valid:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "signal": result_signal,
                    "detail": f"File '{upload_file.filename}' is not supported.",
                },
            )

        _ = ProjectController().get_project_path(project_id=project_id)
        file_path, file_id = data_controller.generate_unique_filepath(
            orig_file_name=upload_file.filename,
            project_id=project_id
        )

        try:
            async with aiofiles.open(file_path, "wb") as f:
                while chunk := await upload_file.read(app_settings.FILE_DEFAULT_CHUNK_SIZE):
                    await f.write(chunk)
        except Exception as exc:
            logger.error("Error while uploading file: %s", exc)
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "signal": ResponseSignal.FILE_UPLOAD_FAILED.value,
                    "detail": f"Error while uploading file '{upload_file.filename}'."
                }
            )

        asset_resource = Asset(
            asset_project_id=project.project_id,
            asset_user_id=current_user.id,
            asset_type=AssetTypeEnum.FILE.value,
            asset_name=file_id,
            asset_size=os.path.getsize(file_path),
            asset_is_private=(vis == "private"),
            asset_visibility=vis,
            asset_department=effective_department,
            asset_document_type=normalized_doc_type,
            asset_config={
                "original_filename": upload_file.filename
            },
        )
        asset_record = await asset_model.create_asset(asset=asset_resource)

        process_controller = ProcessController(project_id=project_id)
        file_content = process_controller.get_file_content(file_id=file_id)

        if file_content is None:
            logger.error("Error while processing uploaded file: %s", file_id)
            await asset_model.delete_asset(asset_record)
            if os.path.exists(file_path):
                os.remove(file_path)
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "signal": ResponseSignal.PROCESSING_FAILED.value,
                    "detail": f"Error while processing file '{upload_file.filename}'."
                }
            )

        file_chunks = process_controller.process_file_content(
            file_content=file_content,
            file_id=file_id,
            chunk_size=chunk_size,
            overlap_size=overlap_size
        )

        if not file_chunks:
            await asset_model.delete_asset(asset_record)
            if os.path.exists(file_path):
                os.remove(file_path)
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "signal": ResponseSignal.PROCESSING_FAILED.value,
                    "detail": f"Failed to split file '{upload_file.filename}' into chunks."
                }
            )

        existing_chunk_ids = set(
            await chunk_model.get_chunk_ids_by_asset_ids([asset_record.asset_id])
        )

        file_chunks_records = [
            DataChunk(
                chunk_text=chunk.page_content,
                chunk_metadata={
                    **(chunk.metadata or {}),
                    "doc_type": normalized_doc_type,
                    "asset_id": asset_record.asset_id,
                    "source_name": upload_file.filename,
                    "original_filename": upload_file.filename,
                },
                chunk_order=i + 1,
                chunk_project_id=project.project_id,
                chunk_asset_id=asset_record.asset_id,
            )
            for i, chunk in enumerate(file_chunks)
        ]

        await chunk_model.insert_many_chunks(file_chunks_records)

        updated_chunk_ids = set(
            await chunk_model.get_chunk_ids_by_asset_ids([asset_record.asset_id])
        )
        new_chunk_ids = sorted(updated_chunk_ids - existing_chunk_ids)
        new_chunks = await chunk_model.get_chunks_by_ids(new_chunk_ids)

        nlp_controller = NLPController(
            vectordb_client=request.app.vectordb_client,
            generation_client=request.app.generation_client,
            embedding_client=request.app.embedding_client,
            template_parser=request.app.template_parser,
        )

        indexed = await nlp_controller.index_into_vector_db(
            project=project,
            chunks=new_chunks,
            chunks_ids=new_chunk_ids,
            do_reset=bool(do_reset),
        )

        if not indexed:
            await chunk_model.delete_chunks_by_asset_ids([asset_record.asset_id])
            await asset_model.delete_asset(asset_record)
            await request.app.vectordb_client.delete_records(
                nlp_controller.create_collection_name(project.project_id),
                new_chunk_ids,
            )
            if os.path.exists(file_path):
                os.remove(file_path)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "signal": ResponseSignal.INSERT_INTO_VECTORDB_ERROR.value,
                    "detail": f"Failed to index chunks for '{upload_file.filename}' into the vector database.",
                },
            )

        results.append(
            {
                "asset_id": asset_record.asset_id,
                "stored_file_name": asset_record.asset_name,
                "original_file_name": upload_file.filename,
                "visibility": vis,
                "department": effective_department,
                "indexed_chunks": len(new_chunk_ids),
            }
        )

    return JSONResponse(
        content={
            "signal": ResponseSignal.INSERT_INTO_VECTORDB_SUCCESS.value,
            "files": results,
        }
    )

@data_router.post("/process/{project_id}")
async def process_endpoint(
    request: Request,
    project_id: int,
    process_request: ProcessRequest,
    current_user: User = Depends(get_current_user),
):

    chunk_size = process_request.chunk_size
    overlap_size = process_request.overlap_size
    do_reset = process_request.do_reset

    project_model = await ProjectModel.create_instance(
        db_client=request.app.db_client
    )

    project, status_code = await project_model.get_project_or_create_one(
        project_id=project_id,
        current_user=current_user,
        create_if_missing=False,
        is_private=process_request.is_private,
        require_owner=True,
    )
    
    nlp_controller = NLPController(
        vectordb_client=request.app.vectordb_client,
        generation_client=request.app.generation_client,
        embedding_client=request.app.embedding_client,
        template_parser=request.app.template_parser,
    )
    if project is None:
        response_status = status.HTTP_403_FORBIDDEN if status_code == "forbidden" else status.HTTP_404_NOT_FOUND
        response_signal = ResponseSignal.ACCESS_FORBIDDEN_ERROR.value if status_code == "forbidden" else ResponseSignal.PROJECT_NOT_FOUND_ERROR.value
        return JSONResponse(
            status_code=response_status,
            content={
                "signal": response_signal,
            }
        )

    asset_model = await AssetModel.create_instance(
            db_client=request.app.db_client
        )

    project_files_info = {}
    if process_request.file_id:
        asset_record, record_exists = await asset_model.get_asset_record(
            asset_project_id=project.project_id,
            asset_name=process_request.file_id,
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

        original_name = get_asset_display_name(asset_record) or asset_record.asset_name
        project_files_info = {
            asset_record.asset_id: {
                "name": asset_record.asset_name,
                "doc_type": asset_record.asset_document_type or DOCUMENT_TYPE_DEFAULT,
                "original_name": original_name,
            }
        }
    
    else:
        project_files = await asset_model.get_all_project_assets(
            asset_project_id=project.project_id,
            asset_type=AssetTypeEnum.FILE.value,
            current_user=current_user,
        )

        project_files_info = {
            record.asset_id: {
                "name": record.asset_name,
                "doc_type": record.asset_document_type or DOCUMENT_TYPE_DEFAULT,
                "original_name": get_asset_display_name(record) or record.asset_name,
            }
            for record in project_files
        }

    if len(project_files_info) == 0:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "signal": ResponseSignal.NO_FILES_ERROR.value,
            }
        )
    
    process_controller = ProcessController(project_id=project_id)

    no_records = 0
    no_files = 0

    chunk_model = await ChunkModel.create_instance(
                        db_client=request.app.db_client
                    )

    if do_reset == 1:
        _ = await chunk_model.delete_chunks_by_project_id(
            project_id=project.project_id
        )

    for asset_id, file_info in project_files_info.items():

        file_id = file_info["name"]
        document_type = file_info["doc_type"]

        file_content = process_controller.get_file_content(file_id=file_id)

        if file_content is None:
            logger.error(f"Error while processing file: {file_id}")
            continue

        file_chunks = process_controller.process_file_content(
            file_content=file_content,
            file_id=file_id,
            chunk_size=chunk_size,
            overlap_size=overlap_size
        )

        if file_chunks is None or len(file_chunks) == 0:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "signal": ResponseSignal.PROCESSING_FAILED.value
                }
            )

        original_name = file_info.get("original_name") or file_id

        file_chunks_records = [
            DataChunk(
                chunk_text=chunk.page_content,
                chunk_metadata={
                    **(chunk.metadata or {}),
                    "doc_type": document_type,
                    "asset_id": asset_id,
                    "source_name": original_name,
                    "original_filename": original_name,
                },
                chunk_order=i+1,
                chunk_project_id=project.project_id,
                chunk_asset_id=asset_id
            )
            for i, chunk in enumerate(file_chunks)
        ]

        no_records += await chunk_model.insert_many_chunks(chunks=file_chunks_records)
        no_files += 1

    return JSONResponse(
        content={
            "signal": ResponseSignal.PROCESSING_SUCCESS.value,
            "inserted_chunks": no_records,
            "processed_files": no_files
        }
    )

@data_router.get("/assets")
async def list_assets(
    request: Request,
    project_id: int = Query(None),
    current_user: User = Depends(get_current_user),
):
    asset_model = await AssetModel.create_instance(
        db_client=request.app.db_client
    )

    if project_id is not None:
        project_model = await ProjectModel.create_instance(
            db_client=request.app.db_client
        )

        project, status_code = await project_model.get_project_or_create_one(
            project_id=project_id,
            current_user=current_user,
            create_if_missing=False,
            is_private=None
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

        assets = await asset_model.get_all_project_assets(
            asset_project_id=project.project_id,
            asset_type=AssetTypeEnum.FILE.value,
            current_user=current_user
        )
    else:
        assets = await asset_model.get_all_accessible_assets(
            asset_type=AssetTypeEnum.FILE.value,
            current_user=current_user
        )

    payload = []
    for asset in assets:
        original_name = get_asset_display_name(asset)

        payload.append(
            {
                "asset_id": asset.asset_id,
                "project_id": asset.asset_project_id,
                "user_id": asset.asset_user_id,
                "name": asset.asset_name,
                "original_name": original_name,
                "doc_type": asset.asset_document_type or DOCUMENT_TYPE_DEFAULT,
                "is_private": asset.asset_is_private,
                "visibility": getattr(asset, "asset_visibility", None),
                "department": getattr(asset, "asset_department", None),
                "size": asset.asset_size,
                "created_at": asset.created_at.isoformat() if getattr(asset, "created_at", None) else None,
                "updated_at": asset.updated_at.isoformat() if getattr(asset, "updated_at", None) else None,
            }
        )

    return JSONResponse(
        content={
            "signal": ResponseSignal.FILE_LIST_SUCCESS.value,
            "assets": payload,
            "no_of_assets": len(payload),
        }
    )
    
@data_router.delete("/assets/{asset_id}")
async def delete_asset(
    request: Request,
    asset_id: int,
    current_user: User = Depends(get_current_user),
):
    asset_model = await AssetModel.create_instance(
        db_client=request.app.db_client
    )

    asset_record, exists_or_forbidden = await asset_model.get_asset_by_id(
        asset_id=asset_id,
        current_user=current_user
    )

    if asset_record is None:
        if exists_or_forbidden:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "signal": ResponseSignal.ACCESS_FORBIDDEN_ERROR.value
                }
            )
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "signal": ResponseSignal.FILE_ID_ERROR.value
            }
        )

    # Only the owner of the file or an admin can delete it,
    # even if the file is public/global.
    is_owner = asset_record.asset_user_id == getattr(current_user, "id", None)
    is_admin = getattr(current_user, "is_admin", False)
    if not (is_owner or is_admin):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "signal": ResponseSignal.ACCESS_FORBIDDEN_ERROR.value,
                "detail": "Only the file owner or an admin can delete this file.",
            },
        )

    chunk_model = await ChunkModel.create_instance(
        db_client=request.app.db_client
    )

    chunk_ids = await chunk_model.get_chunk_ids_by_asset_ids([asset_record.asset_id])

    if chunk_ids:
        nlp_controller = NLPController(
            vectordb_client=request.app.vectordb_client,
            generation_client=request.app.generation_client,
            embedding_client=request.app.embedding_client,
            template_parser=request.app.template_parser,
        )
        collection_name = nlp_controller.create_collection_name(
            project_id=asset_record.asset_project_id
        )
        await request.app.vectordb_client.delete_records(collection_name, chunk_ids)

    await chunk_model.delete_chunks_by_asset_ids([asset_record.asset_id])
    await asset_model.delete_asset(asset_record)

    return JSONResponse(
        content={
            "signal": ResponseSignal.FILE_DELETE_SUCCESS.value
        }
    )
