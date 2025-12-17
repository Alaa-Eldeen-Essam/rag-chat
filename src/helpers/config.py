from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    APP_NAME: str
    APP_VERSION: str

    FILE_ALLOWED_TYPES: list
    FILE_MAX_SIZE: int
    FILE_DEFAULT_CHUNK_SIZE: int

    POSTGRES_USERNAME: str
    POSTGRES_PASSWORD: str
    POSTGRES_HOST: str
    POSTGRES_PORT: int
    POSTGRES_MAIN_DATABASE: str

    GENERATION_BACKEND: str
    EMBEDDING_BACKEND: str

    OPENAI_API_KEY: Optional[str] = None
    OPENAI_API_URL: Optional[str] = None
    HF_TOKEN: Optional[str] = None
    HF_HUB_OFFLINE: Optional[bool] = None
    # Role-specific / engine-specific OpenAI-style endpoints
    GENERATION_API_URL: Optional[str] = None
    EMBEDDING_API_URL: Optional[str] = None
    OLLAMA_API_URL: Optional[str] = None
    OLLAMA_CHAT_API_URL: Optional[str] = None
    OLLAMA_EMBED_API_URL: Optional[str] = None
    OLLAMA_RERANKER_API_URL: Optional[str] = None
    VLLM_API_URL: Optional[str] = None

    GENERATION_MODEL_ID: Optional[str] = None
    BEST_GENERATION_MODEL_ID: Optional[str] = None
    THINKING_GENERATION_MODEL_ID: Optional[str] = None
    FAST_GENERATION_MODEL_ID: Optional[str] = None
    DEFAULT_GENERATION_MODEL_KEY: Optional[str] = None
    EMBEDDING_MODEL_ID: Optional[str] = None
    EMBEDDING_MODEL_SIZE: Optional[int] = None
    INPUT_DAFAULT_MAX_CHARACTERS: Optional[int] = None
    GENERATION_DAFAULT_MAX_TOKENS: Optional[int] = None
    GENERATION_DAFAULT_TEMPERATURE: Optional[float] = None
    SUMMARY_DEFAULT_MAX_TOKENS: Optional[int] = None

    # Engine-specific model IDs (Ollama)
    OLLAMA_GENERATION_MODEL_ID: Optional[str] = None
    OLLAMA_BEST_GENERATION_MODEL_ID: Optional[str] = None
    OLLAMA_THINKING_GENERATION_MODEL_ID: Optional[str] = None
    OLLAMA_FAST_GENERATION_MODEL_ID: Optional[str] = None
    OLLAMA_EMBEDDING_MODEL_ID: Optional[str] = None

    # Engine-specific model IDs (vLLM)
    VLLM_GENERATION_MODEL_ID: Optional[str] = None
    VLLM_BEST_GENERATION_MODEL_ID: Optional[str] = None
    VLLM_THINKING_GENERATION_MODEL_ID: Optional[str] = None
    VLLM_FAST_GENERATION_MODEL_ID: Optional[str] = None
    VLLM_EMBEDDING_MODEL_ID: Optional[str] = None

    VECTOR_DB_BACKEND_LITERAL: Optional[List[str]] = None
    VECTOR_DB_BACKEND: str
    VECTOR_DB_DISTANCE_METHOD: Optional[str] = None
    VECTOR_DB_PGVEC_INDEX_THRESHOLD: int = 100

    # OCR / Tesseract configuration
    OCR_ENABLED: bool = False
    OCR_LANGS: str = "eng+ara"
    OCR_MAX_PAGES: Optional[int] = None
    OCR_DPI: Optional[int] = 300

    PRIMARY_LANG: str = "en"
    DEFAULT_LANG: str = "en"

    # JWT / auth
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # Search / Elasticsearch
    ELASTICSEARCH_URL: Optional[str] = None
    ELASTICSEARCH_INDEX_PREFIX: Optional[str] = None

    # Reranker
    RERANKER_ENABLED: bool = False
    RERANKER_API_URL: Optional[str] = None
    RERANKER_API_KEY: Optional[str] = None
    RERANKER_MODEL_ID: Optional[str] = None
    RERANKER_MAX_CANDIDATES: int = 50

    # Prompt guard
    PROMPT_GUARD_ENABLED: bool = True
    PROMPT_GUARD_PYTECTOR: bool = False
    PROMPT_GUARD_PYTECTOR_MODEL: Optional[str] = None
    PROMPT_GUARD_PYTECTOR_THRESHOLD: float = 0.75
    PROMPT_GUARD_BYPASS_HEADER: str = "X-Bypass-Prompt-Guard"

def get_settings() -> Settings:
    return Settings()
