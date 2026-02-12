from pathlib import Path
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from routes import auth, base, data, nlp, users, stats
from helpers.config import get_settings
from stores.llm.LLMProviderFactory import LLMProviderFactory
from stores.llm.providers.RerankerProvider import RerankerProvider
from stores.llm.providers.OllamaCliRerankerProvider import OllamaCliRerankerProvider
from stores.llm.providers.CrossEncoderRerankerProvider import CrossEncoderRerankerProvider
from stores.vectordb.VectorDBProviderFactory import VectorDBProviderFactory
from stores.llm.templates.template_parser import TemplateParser
from stores.search import SearchProviderFactory
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from models.UserModel import UserModel
from helpers.security import hash_password
from utils.metrics import setup_metrics

app = FastAPI()
logger = logging.getLogger(__name__)

setup_metrics(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

async def startup_span():
    settings = get_settings()

    postgres_conn = f"postgresql+asyncpg://{settings.POSTGRES_USERNAME}:{settings.POSTGRES_PASSWORD}@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_MAIN_DATABASE}"

    app.db_engine = create_async_engine(postgres_conn)
    app.db_client = sessionmaker(
        app.db_engine, class_=AsyncSession, expire_on_commit=False
    )

    llm_provider_factory = LLMProviderFactory(settings)
    vectordb_provider_factory = VectorDBProviderFactory(config=settings, db_client=app.db_client)
    search_provider_factory = SearchProviderFactory(settings)

    # Decide which engine's model IDs to use for generation based on the
    # configured GENERATION_API_URL.
    ollama_chat_url = (
        getattr(settings, "OLLAMA_CHAT_API_URL", None)
        or getattr(settings, "OLLAMA_API_URL", None)
    )
    use_ollama_for_gen = (
        getattr(settings, "GENERATION_API_URL", None)
        and ollama_chat_url
        and settings.GENERATION_API_URL.strip() == ollama_chat_url.strip()
    )

    if use_ollama_for_gen:
        base_generation_model_id = settings.OLLAMA_GENERATION_MODEL_ID
        best_generation_model_id = settings.OLLAMA_BEST_GENERATION_MODEL_ID or base_generation_model_id
        thinking_generation_model_id = settings.OLLAMA_THINKING_GENERATION_MODEL_ID
        fast_generation_model_id = settings.OLLAMA_FAST_GENERATION_MODEL_ID
    else:
        base_generation_model_id = settings.VLLM_GENERATION_MODEL_ID
        best_generation_model_id = settings.VLLM_BEST_GENERATION_MODEL_ID or base_generation_model_id
        thinking_generation_model_id = settings.VLLM_THINKING_GENERATION_MODEL_ID
        fast_generation_model_id = settings.VLLM_FAST_GENERATION_MODEL_ID

    generation_models = {
        "best": best_generation_model_id,
        "thinking": thinking_generation_model_id,
        "fast": fast_generation_model_id,
    }
    generation_models = {key: value for key, value in generation_models.items() if value}

    if not generation_models:
        raise ValueError("No generation models configured. Please update environment variables.")

    default_model_key = settings.DEFAULT_GENERATION_MODEL_KEY.lower() if settings.DEFAULT_GENERATION_MODEL_KEY else None
    if not default_model_key or default_model_key not in generation_models:
        default_model_key = "best" if "best" in generation_models else next(iter(generation_models.keys()))

    app.generation_model_ids = generation_models
    app.default_generation_model_key = default_model_key
    app.generation_clients = {}

    for key, model_id in generation_models.items():
        client = llm_provider_factory.create_generation_client()
        client.set_generation_model(model_id=model_id)
        app.generation_clients[key] = client

    app.generation_client = app.generation_clients[default_model_key]

    # embedding client
    app.embedding_client = llm_provider_factory.create_embedding_client()
    # Decide which engine's embedding model ID to use based on the configured EMBEDDING_API_URL.
    ollama_embed_url = (
        getattr(settings, "OLLAMA_EMBED_API_URL", None)
        or getattr(settings, "OLLAMA_API_URL", None)
    )
    use_ollama_for_embed = (
        getattr(settings, "EMBEDDING_API_URL", None)
        and ollama_embed_url
        and settings.EMBEDDING_API_URL.strip() == ollama_embed_url.strip()
    )

    if use_ollama_for_embed:
        embedding_model_id = settings.OLLAMA_EMBEDDING_MODEL_ID
    else:
        embedding_model_id = settings.VLLM_EMBEDDING_MODEL_ID

    app.embedding_client.set_embedding_model(
        model_id=embedding_model_id,
        embedding_size=settings.EMBEDDING_MODEL_SIZE,
    )
    
    # vector db client
    app.vectordb_client = vectordb_provider_factory.create(
        provider=settings.VECTOR_DB_BACKEND
    )
    await app.vectordb_client.connect()

    # search client (Elasticsearch)
    app.search_client = search_provider_factory.create()
    if app.search_client is not None:
        await app.search_client.connect()

    app.template_parser = TemplateParser(
        language=settings.PRIMARY_LANG,
        default_language=settings.DEFAULT_LANG,
    )

    app.reranker_client = None
    app.reranker_max_candidates = settings.RERANKER_MAX_CANDIDATES or 0
    reranker_backend = (getattr(settings, "RERANKER_BACKEND", None) or "").strip().lower()

    if getattr(settings, "RERANKER_ENABLED", False):
        if reranker_backend == "ollama_cli":
            model_id = settings.OLLAMA_RERANKER_MODEL_ID or settings.RERANKER_MODEL_ID
            ollama_host = settings.OLLAMA_RERANKER_HOST
            if not ollama_host:
                candidate_url = (
                    getattr(settings, "OLLAMA_CHAT_API_URL", None)
                    or getattr(settings, "OLLAMA_API_URL", None)
                )
                if candidate_url:
                    ollama_host = candidate_url.rstrip("/")
                    if ollama_host.endswith("/v1"):
                        ollama_host = ollama_host[: -len("/v1")]
            if model_id:
                app.reranker_client = OllamaCliRerankerProvider(
                    model_id=model_id,
                    timeout=settings.RERANKER_TIMEOUT or 30.0,
                    ollama_host=ollama_host,
                )
        elif reranker_backend == "cross_encoder":
            model_id = settings.RERANKER_MODEL_ID or "cross-encoder/ms-marco-MiniLM-L-6-v2"
            fallback_model_id = getattr(settings, "RERANKER_FALLBACK_MODEL_ID", None) or "cross-encoder/ms-marco-MiniLM-L-6-v2"
            try:
                app.reranker_client = CrossEncoderRerankerProvider(
                    model_id=model_id,
                    fallback_model_id=fallback_model_id,
                )
            except Exception as exc:
                logger.error("Failed to load cross-encoder reranker: %s", exc)
                app.reranker_client = None
        else:
            reranker_api_url = settings.RERANKER_API_URL
            if not reranker_api_url and getattr(settings, "OLLAMA_RERANKER_API_URL", None):
                reranker_api_url = f"{settings.OLLAMA_RERANKER_API_URL.rstrip('/')}/rerank"

            if reranker_api_url and settings.RERANKER_MODEL_ID:
                app.reranker_client = RerankerProvider(
                    api_url=reranker_api_url,
                    api_key=settings.RERANKER_API_KEY,
                    model_id=settings.RERANKER_MODEL_ID,
                )

    user_model = await UserModel.create_instance(
        db_client=app.db_client
    )
    await user_model.ensure_initial_admin(
        username="admin",
        password_hash=hash_password("admin123"),
    )    

async def shutdown_span():
    await app.db_engine.dispose()
    await app.vectordb_client.disconnect()
    search_client = getattr(app, "search_client", None)
    if search_client is not None:
        await search_client.disconnect()

app.on_event("startup")(startup_span)
app.on_event("shutdown")(shutdown_span)

app.include_router(base.base_router)
app.include_router(auth.auth_router)
app.include_router(data.data_router)
app.include_router(nlp.nlp_router)
app.include_router(users.users_router)
app.include_router(stats.stats_router)

# --- Frontend static serving (built React app) ---
# Support both local dev layout (src/main.py, frontend/dist at project root)
# and Docker layout (/app/main.py, frontend/dist under /app).
src_dir = Path(__file__).resolve().parent
frontend_candidates = [
    src_dir.parent / "frontend" / "dist",  # e.g. repo_root/frontend/dist
    src_dir / "frontend" / "dist",         # e.g. /app/frontend/dist in Docker
]

frontend_dist_path = next((p for p in frontend_candidates if p.exists()), None)

if frontend_dist_path is not None:
    app.mount(
        "/app",
        StaticFiles(directory=str(frontend_dist_path), html=True),
        name="frontend",
    )

    @app.get("/", include_in_schema=False)
    async def root_redirect():
        return RedirectResponse(url="/app")
