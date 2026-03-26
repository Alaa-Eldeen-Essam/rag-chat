from fastapi import FastAPI, APIRouter, Depends
import os
from helpers.config import get_settings, Settings

base_router = APIRouter(
    prefix="/api/v1",
    tags=["api_v1"],
)

# Attach generation model info to the router for access in endpoints
@base_router.get("/")
async def app_info():
    settings = get_settings()
    return {
        "app_name": settings.APP_NAME,
        "app_version": settings.APP_VERSION,
        "generation_backend": settings.GENERATION_BACKEND,
        "embedding_backend": settings.EMBEDDING_BACKEND,
        "vector_db_backend": settings.VECTOR_DB_BACKEND,
        "generation_models": settings.GENERATION_MODEL_ID,
        "default_generation_model_key": settings.DEFAULT_GENERATION_MODEL_KEY,
        "embedding_models": settings.EMBEDDING_MODEL_ID,
        "embedding_model_size": settings.EMBEDDING_MODEL_SIZE,
        "db_status": "configured" if settings.POSTGRES_MAIN_DATABASE else "not configured",
    }
@base_router.get("/ready")
async def readiness():
    return {"status": "ok"}