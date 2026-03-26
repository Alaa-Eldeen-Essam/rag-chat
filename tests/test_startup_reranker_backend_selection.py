import asyncio
import contextlib
import importlib.util
import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.append(str(SRC_ROOT))

_module = None
IMPORT_ERROR = None
try:
    _spec = importlib.util.spec_from_file_location("main", SRC_ROOT / "main.py")
    _module = importlib.util.module_from_spec(_spec)
    assert _spec and _spec.loader
    _spec.loader.exec_module(_module)
except Exception as exc:  # pragma: no cover - environment dependent
    _module = None
    IMPORT_ERROR = exc


class _DummyGenerationClient:
    def set_generation_model(self, model_id):
        self.model_id = model_id


class _DummyEmbeddingClient:
    def set_embedding_model(self, model_id, embedding_size):
        self.model_id = model_id
        self.embedding_size = embedding_size


class _DummyLlmFactory:
    def __init__(self, settings):
        self.settings = settings

    def create_generation_client(self):
        return _DummyGenerationClient()

    def create_embedding_client(self):
        return _DummyEmbeddingClient()


class _DummyVectorClient:
    async def connect(self):
        return None

    async def disconnect(self):
        return None


class _DummyVectorFactory:
    def __init__(self, config, db_client):
        self.config = config
        self.db_client = db_client

    def create(self, provider):
        return _DummyVectorClient()


class _DummySearchFactory:
    def __init__(self, settings):
        self.settings = settings

    def create(self):
        return None


class _DummyEngine:
    async def dispose(self):
        return None


class _DummyUserModel:
    async def ensure_initial_admin(self, username, password_hash):
        return None


def _build_settings(reranker_enabled: bool, reranker_backend: str) -> SimpleNamespace:
    return SimpleNamespace(
        POSTGRES_USERNAME="postgres",
        POSTGRES_PASSWORD="postgres",
        POSTGRES_HOST="localhost",
        POSTGRES_PORT=5432,
        POSTGRES_MAIN_DATABASE="minirag",
        GENERATION_API_URL="http://ollama.local:11434/v1",
        OLLAMA_CHAT_API_URL="http://ollama.local:11434/v1",
        OLLAMA_API_URL="http://ollama.local:11434/v1",
        OLLAMA_GENERATION_MODEL_ID="chat-model",
        OLLAMA_BEST_GENERATION_MODEL_ID="chat-model",
        OLLAMA_THINKING_GENERATION_MODEL_ID=None,
        OLLAMA_FAST_GENERATION_MODEL_ID=None,
        VLLM_GENERATION_MODEL_ID="vllm-chat-model",
        VLLM_BEST_GENERATION_MODEL_ID="vllm-chat-model",
        VLLM_THINKING_GENERATION_MODEL_ID=None,
        VLLM_FAST_GENERATION_MODEL_ID=None,
        DEFAULT_GENERATION_MODEL_KEY="best",
        EMBEDDING_API_URL="http://ollama.local:11434/v1",
        OLLAMA_EMBED_API_URL="http://ollama.local:11434/v1",
        OLLAMA_EMBEDDING_MODEL_ID="embed-model",
        VLLM_EMBEDDING_MODEL_ID="vllm-embed-model",
        EMBEDDING_MODEL_SIZE=1024,
        VECTOR_DB_BACKEND="PGVECTOR",
        PRIMARY_LANG="en",
        DEFAULT_LANG="en",
        RERANKER_ENABLED=reranker_enabled,
        RERANKER_BACKEND=reranker_backend,
        RERANKER_MODEL_ID="BAAI/bge-reranker-v2-m3",
        RERANKER_FALLBACK_MODEL_ID="cross-encoder/ms-marco-MiniLM-L-6-v2",
        RERANKER_MAX_CANDIDATES=25,
        INITIAL_ADMIN_BOOTSTRAP=False,
        INITIAL_ADMIN_USERNAME="admin",
        INITIAL_ADMIN_PASSWORD_HASH="",
        INITIAL_ADMIN_PASSWORD=None,
    )


@unittest.skipIf(_module is None, f"main import failed: {IMPORT_ERROR}")
class StartupRerankerBackendSelectionTests(unittest.TestCase):
    @contextlib.contextmanager
    def _common_patches(self, settings: SimpleNamespace):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(_module, "get_settings", return_value=settings))
            stack.enter_context(
                patch.object(_module, "create_async_engine", return_value=_DummyEngine())
            )
            stack.enter_context(patch.object(_module, "sessionmaker", return_value=object()))
            stack.enter_context(patch.object(_module, "LLMProviderFactory", _DummyLlmFactory))
            stack.enter_context(
                patch.object(_module, "VectorDBProviderFactory", _DummyVectorFactory)
            )
            stack.enter_context(
                patch.object(_module, "SearchProviderFactory", _DummySearchFactory)
            )
            stack.enter_context(
                patch.object(_module, "TemplateParser", return_value=object())
            )
            stack.enter_context(
                patch.object(
                    _module.UserModel,
                    "create_instance",
                    new=AsyncMock(return_value=_DummyUserModel()),
                )
            )
            yield stack

    def test_cross_encoder_backend_initializes_reranker_client(self):
        settings = _build_settings(reranker_enabled=True, reranker_backend="cross_encoder")
        reranker_client = object()

        with self._common_patches(settings):
            with patch.object(
                _module,
                "CrossEncoderRerankerProvider",
                return_value=reranker_client,
            ) as mock_provider:
                asyncio.run(_module.startup_span())

        self.assertIs(_module.app.reranker_client, reranker_client)
        mock_provider.assert_called_once_with(
            model_id="BAAI/bge-reranker-v2-m3",
            fallback_model_id="cross-encoder/ms-marco-MiniLM-L-6-v2",
        )

    def test_unsupported_backend_disables_reranker_with_warning(self):
        settings = _build_settings(reranker_enabled=True, reranker_backend="ollama_cli")

        with self._common_patches(settings):
            with patch.object(_module.logger, "warning") as mock_warning:
                with patch.object(_module, "CrossEncoderRerankerProvider") as mock_provider:
                    asyncio.run(_module.startup_span())

        self.assertIsNone(_module.app.reranker_client)
        mock_provider.assert_not_called()
        self.assertTrue(
            any(
                "Unsupported reranker backend" in str(call.args[0])
                for call in mock_warning.call_args_list
                if call.args
            )
        )

    def test_cross_encoder_load_failure_does_not_crash_startup(self):
        settings = _build_settings(reranker_enabled=True, reranker_backend="cross_encoder")

        with self._common_patches(settings):
            with patch.object(
                _module,
                "CrossEncoderRerankerProvider",
                side_effect=RuntimeError("load failed"),
            ):
                with patch.object(_module.logger, "error") as mock_error:
                    asyncio.run(_module.startup_span())

        self.assertIsNone(_module.app.reranker_client)
        self.assertTrue(
            any(
                "Failed to load cross-encoder reranker" in str(call.args[0])
                for call in mock_error.call_args_list
                if call.args
            )
        )


if __name__ == "__main__":
    unittest.main()
