import asyncio
import pathlib
import sys
import types
import importlib.util
import os
import unittest
from types import SimpleNamespace

SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.append(str(SRC_ROOT))

os.environ.setdefault("APP_NAME", "test")
os.environ.setdefault("APP_VERSION", "0.1")
os.environ.setdefault("FILE_ALLOWED_TYPES", "[\"application/pdf\"]")
os.environ.setdefault("FILE_MAX_SIZE", "10")
os.environ.setdefault("FILE_DEFAULT_CHUNK_SIZE", "1024")
os.environ.setdefault("POSTGRES_USERNAME", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_MAIN_DATABASE", "test")
os.environ.setdefault("GENERATION_BACKEND", "OPENAI")
os.environ.setdefault("EMBEDDING_BACKEND", "OPENAI")
os.environ.setdefault("VECTOR_DB_BACKEND", "PGVECTOR")

if "controllers" not in sys.modules:
    controllers_pkg = types.ModuleType("controllers")
    controllers_pkg.__path__ = [str(SRC_ROOT / "controllers")]
    sys.modules["controllers"] = controllers_pkg

if "models.db_schemes" not in sys.modules:
    db_schemes_stub = types.ModuleType("models.db_schemes")

    class DataChunk:  # pragma: no cover - test stub
        pass

    class Project:  # pragma: no cover - test stub
        pass

    class RetrievedDocument:  # pragma: no cover - test stub
        pass

    db_schemes_stub.DataChunk = DataChunk
    db_schemes_stub.Project = Project
    db_schemes_stub.RetrievedDocument = RetrievedDocument
    sys.modules["models.db_schemes"] = db_schemes_stub

NLPController = None
IMPORT_ERROR = None
try:
    _spec = importlib.util.spec_from_file_location(
        "controllers.NLPController",
        SRC_ROOT / "controllers" / "NLPController.py",
    )
    _module = importlib.util.module_from_spec(_spec)
    sys.modules["controllers.NLPController"] = _module
    assert _spec and _spec.loader
    _spec.loader.exec_module(_module)
    NLPController = _module.NLPController
except Exception as exc:  # pragma: no cover - environment dependent
    IMPORT_ERROR = exc


class _DummyGenerationClient:
    class enums:
        pass

    def process_text(self, text: str) -> str:
        return text

    def construct_prompt(self, prompt: str, role: str):
        return {"role": role, "content": prompt}

    def generate_text(self, prompt: str, chat_history: list, temperature: float = 0.0) -> str:
        return "hop summary"


class _EnumValue:
    def __init__(self, value: str):
        self.value = value


_DummyGenerationClient.enums.SYSTEM = _EnumValue("system")
_DummyGenerationClient.enums.USER = _EnumValue("user")
_DummyGenerationClient.enums.ASSISTANT = _EnumValue("assistant")


class _DummyTemplateParser:
    language = "en"

    def get(self, group: str, key: str, vars: dict | None = None):
        if key == "system_prompt":
            return "System prompt"
        if key == "hop_summary_prompt":
            return "Hop summary prompt"
        return None


class _TrackingController(NLPController):
    def __init__(self):
        super().__init__(
            vectordb_client=object(),
            generation_client=_DummyGenerationClient(),
            embedding_client=object(),
            template_parser=_DummyTemplateParser(),
        )
        self.search_calls: list[tuple[int, str]] = []
        self.captured_docs: list = []

    async def search_vector_db_collection(
        self,
        project,
        text: str,
        limit: int,
        doc_types=None,
        asset_ids=None,
        keywords=None,
    ):
        project_id = int(getattr(project, "project_id", 0) or 0)
        self.search_calls.append((project_id, text))
        if "CTX_MARKER" in (text or ""):
            return [
                SimpleNamespace(
                    text=f"history evidence p{project_id}",
                    score=1.0,
                    metadata={
                        "chunk_id": 2000 + project_id,
                        "project_id": project_id,
                        "asset_id": project_id,
                    },
                ),
            ]
        return [
            SimpleNamespace(
                text=f"query evidence p{project_id}",
                score=1.0,
                metadata={
                    "chunk_id": 1000 + project_id,
                    "project_id": project_id,
                    "asset_id": project_id,
                },
            ),
        ]

    async def generate_rag_answer_from_documents(
        self,
        retrieved_documents,
        query,
        chat_messages=None,
        stream=False,
        collector=None,
        asset_labels=None,
        asset_labels_by_name=None,
        direct_hint=None,
        answer_style=None,
        explain_retrieval=False,
        template_group="rag",
        conversation_context=None,
        ambiguity_threshold=None,
        force_clarification=None,
    ):
        self.captured_docs = list(retrieved_documents)
        return "answer", None, [], {
            "needs_clarification": False,
            "_analysis_source": "llm",
            "_analysis_parse_failed": False,
        }


@unittest.skipIf(NLPController is None, f"NLPController import failed: {IMPORT_ERROR}")
class MultiHopHistoryWeightingTests(unittest.TestCase):
    def test_multihop_prefers_history_aware_results_when_weight_high(self):
        controller = _TrackingController()
        project = SimpleNamespace(project_id=1)
        asyncio.run(
            controller.generate_multihop_rag_answer(
                project=project,
                query="what happened?",
                max_hops=1,
                per_hop_k=3,
                per_hop_evidence=1,
                conversation_context="CTX_MARKER",
                history_weight=0.75,
            )
        )
        self.assertGreaterEqual(len(controller.search_calls), 2)
        self.assertTrue(controller.captured_docs)
        top_chunk_id = int((controller.captured_docs[0].metadata or {}).get("chunk_id"))
        self.assertEqual(top_chunk_id, 2001)

    def test_multihop_prefers_query_results_when_history_weight_zero(self):
        controller = _TrackingController()
        project = SimpleNamespace(project_id=1)
        asyncio.run(
            controller.generate_multihop_rag_answer(
                project=project,
                query="what happened?",
                max_hops=1,
                per_hop_k=3,
                per_hop_evidence=1,
                conversation_context="CTX_MARKER",
                history_weight=0.0,
            )
        )
        self.assertTrue(controller.captured_docs)
        top_chunk_id = int((controller.captured_docs[0].metadata or {}).get("chunk_id"))
        self.assertEqual(top_chunk_id, 1001)

    def test_multihop_project_scope_retrieves_across_projects(self):
        controller = _TrackingController()
        project = SimpleNamespace(project_id=999)
        asyncio.run(
            controller.generate_multihop_rag_answer(
                project=project,
                query="what happened?",
                max_hops=1,
                per_hop_k=3,
                per_hop_evidence=2,
                conversation_context="CTX_MARKER",
                history_weight=0.0,
                project_asset_scope={1: [10], 2: [20]},
            )
        )
        searched_project_ids = {pid for pid, _ in controller.search_calls}
        self.assertIn(1, searched_project_ids)
        self.assertIn(2, searched_project_ids)
        chunk_ids = {
            int((doc.metadata or {}).get("chunk_id"))
            for doc in controller.captured_docs
            if getattr(doc, "metadata", None)
            and (doc.metadata or {}).get("chunk_id") is not None
        }
        self.assertTrue(any(chunk_id in chunk_ids for chunk_id in (1001, 1002)))


if __name__ == "__main__":
    unittest.main()
