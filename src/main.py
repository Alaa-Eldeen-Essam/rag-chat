from fastapi import FastAPI
from routes import base, data, nlp, users, stats
from helpers.config import get_settings
from stores.llm.LLMProviderFactory import LLMProviderFactory
from stores.vectordb.VectorDBProviderFactory import VectorDBProviderFactory
from stores.llm.templates.template_parser import TemplateParser
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from models.UserModel import UserModel
from helpers.security import hash_password

app = FastAPI()

async def startup_span():
    settings = get_settings()

    postgres_conn = f"postgresql+asyncpg://{settings.POSTGRES_USERNAME}:{settings.POSTGRES_PASSWORD}@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_MAIN_DATABASE}"

    app.db_engine = create_async_engine(postgres_conn)
    app.db_client = sessionmaker(
        app.db_engine, class_=AsyncSession, expire_on_commit=False
    )

    llm_provider_factory = LLMProviderFactory(settings)
    vectordb_provider_factory = VectorDBProviderFactory(settings)

    generation_models = {
        "best": settings.BEST_GENERATION_MODEL_ID or settings.GENERATION_MODEL_ID,
        "thinking": settings.THINKING_GENERATION_MODEL_ID,
        "fast": settings.FAST_GENERATION_MODEL_ID,
    }
    generation_models = {
        key: value for key, value in generation_models.items() if value
    }

    if not generation_models:
        raise ValueError("No generation models configured. Please update environment variables.")

    default_model_key = settings.DEFAULT_GENERATION_MODEL_KEY.lower() if settings.DEFAULT_GENERATION_MODEL_KEY else None
    if not default_model_key or default_model_key not in generation_models:
        default_model_key = "best" if "best" in generation_models else next(iter(generation_models.keys()))

    app.generation_model_ids = generation_models
    app.default_generation_model_key = default_model_key
    app.generation_clients = {}

    for key, model_id in generation_models.items():
        client = llm_provider_factory.create(provider=settings.GENERATION_BACKEND)
        client.set_generation_model(model_id=model_id)
        app.generation_clients[key] = client

    app.generation_client = app.generation_clients[default_model_key]

    # embedding client
    app.embedding_client = llm_provider_factory.create(provider=settings.EMBEDDING_BACKEND)
    app.embedding_client.set_embedding_model(model_id=settings.EMBEDDING_MODEL_ID,
                                             embedding_size=settings.EMBEDDING_MODEL_SIZE)
    
    # vector db client
    app.vectordb_client = vectordb_provider_factory.create(
        provider=settings.VECTOR_DB_BACKEND
    )
    app.vectordb_client.connect()

    app.template_parser = TemplateParser(
        language=settings.PRIMARY_LANG,
        default_language=settings.DEFAULT_LANG,
    )

    user_model = await UserModel.create_instance(
        db_client=app.db_client
    )
    await user_model.ensure_initial_admin(
        username="admin",
        password_hash=hash_password("admin123"),
    )

async def shutdown_span():
    app.db_engine.dispose()
    app.vectordb_client.disconnect()

app.on_event("startup")(startup_span)
app.on_event("shutdown")(shutdown_span)

app.include_router(base.base_router)
app.include_router(data.data_router)
app.include_router(nlp.nlp_router)
app.include_router(users.users_router)
app.include_router(stats.stats_router)
