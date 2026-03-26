import asyncio
import os
import pathlib
import sys
import types
import importlib.util
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
MODULE = None
IMPORT_ERROR = None
try:
    _spec = importlib.util.spec_from_file_location(
        "controllers.NLPController",
        SRC_ROOT / "controllers" / "NLPController.py",
    )
    MODULE = importlib.util.module_from_spec(_spec)
    sys.modules["controllers.NLPController"] = MODULE
    assert _spec and _spec.loader
    _spec.loader.exec_module(MODULE)
    NLPController = MODULE.NLPController
except Exception as exc:  # pragma: no cover - environment dependent
    IMPORT_ERROR = exc


class _DummyVectorClient:
    default_vector_size = 8


class _DummyGenerationClient:
    class enums:
        SYSTEM = SimpleNamespace(value="system")
        USER = SimpleNamespace(value="user")
        ASSISTANT = SimpleNamespace(value="assistant")

    def process_text(self, text: str) -> str:
        return text

    def construct_prompt(self, prompt: str, role: str):
        return {"role": role, "content": prompt}


class _DummyEmbeddingClient:
    embedding_size = 8


class _DummyTemplateParser:
    language = "en"

    def get(self, *_args, **_kwargs):
        return None


@unittest.skipIf(NLPController is None, f"NLPController import failed: {IMPORT_ERROR}")
class NlpControllerDelegationTests(unittest.TestCase):
    def _controller(self) -> NLPController:
        return NLPController(
            vectordb_client=_DummyVectorClient(),
            generation_client=_DummyGenerationClient(),
            embedding_client=_DummyEmbeddingClient(),
            template_parser=_DummyTemplateParser(),
        )

    def test_build_lexical_query_delegates(self):
        controller = self._controller()
        old = MODULE.orchestrate_build_lexical_query
        MODULE.orchestrate_build_lexical_query = lambda text: f"delegated:{text}"
        try:
            self.assertEqual(
                controller._build_lexical_query("hello world"),
                "delegated:hello world",
            )
        finally:
            MODULE.orchestrate_build_lexical_query = old

    def test_direct_answer_delegates(self):
        controller = self._controller()
        old = MODULE.orchestrate_try_extract_direct_answer
        MODULE.orchestrate_try_extract_direct_answer = (
            lambda query, documents, question_type: f"{question_type}:{len(documents)}"
        )
        try:
            self.assertEqual(
                controller._try_extract_direct_answer(
                    query="q",
                    documents=[SimpleNamespace(text="x")],
                    question_type="when",
                ),
                "when:1",
            )
        finally:
            MODULE.orchestrate_try_extract_direct_answer = old

    def test_search_delegates(self):
        controller = self._controller()
        captured = {}

        async def fake(self_obj, **kwargs):
            captured.update(kwargs)
            return ["ok"]

        old = MODULE.orchestrate_search_vector_db_collection
        MODULE.orchestrate_search_vector_db_collection = fake
        try:
            result = asyncio.run(
                controller.search_vector_db_collection(
                    project=SimpleNamespace(project_id=5),
                    text="hello",
                    limit=3,
                )
            )
        finally:
            MODULE.orchestrate_search_vector_db_collection = old

        self.assertEqual(result, ["ok"])
        self.assertEqual(captured.get("text"), "hello")
        self.assertEqual(captured.get("limit"), 3)

    def test_analysis_delegates(self):
        controller = self._controller()
        captured = {}

        async def fake(self_obj, **kwargs):
            captured.update(kwargs)
            return {"ok": True}

        old = MODULE.orchestrate_analyze_evidence_for_answer
        MODULE.orchestrate_analyze_evidence_for_answer = fake
        try:
            result = asyncio.run(
                controller.analyze_evidence_for_answer(
                    query="when",
                    retrieved_documents=[],
                    template_group="rag",
                )
            )
        finally:
            MODULE.orchestrate_analyze_evidence_for_answer = old

        self.assertEqual(result, {"ok": True})
        self.assertEqual(captured.get("query"), "when")
        self.assertEqual(captured.get("template_group"), "rag")

    def test_answer_rag_question_delegates(self):
        controller = self._controller()
        captured = {}

        async def fake(self_obj, **kwargs):
            captured.update(kwargs)
            return ("answer", None, None, {"answer_confidence": 1.0})

        old = MODULE.orchestrate_answer_rag_question
        MODULE.orchestrate_answer_rag_question = fake
        try:
            result = asyncio.run(
                controller.answer_rag_question(
                    project=SimpleNamespace(project_id=9),
                    query="when",
                    limit=4,
                )
            )
        finally:
            MODULE.orchestrate_answer_rag_question = old

        self.assertEqual(result[0], "answer")
        self.assertEqual(captured.get("query"), "when")
        self.assertEqual(captured.get("limit"), 4)

    def test_answer_rag_from_documents_delegates(self):
        controller = self._controller()
        captured = {}

        async def fake(self_obj, **kwargs):
            captured.update(kwargs)
            return ("answer", None, None, {"answer_confidence": 1.0})

        old = MODULE.orchestrate_answer_rag_from_documents
        MODULE.orchestrate_answer_rag_from_documents = fake
        try:
            result = asyncio.run(
                controller.answer_rag_from_documents(
                    retrieved_documents=[SimpleNamespace(text="x", metadata={})],
                    query="when",
                    stream=False,
                )
            )
        finally:
            MODULE.orchestrate_answer_rag_from_documents = old

        self.assertEqual(result[0], "answer")
        self.assertEqual(captured.get("query"), "when")
        self.assertEqual(len(captured.get("retrieved_documents") or []), 1)

    def test_index_into_vector_db_delegates(self):
        controller = self._controller()
        captured = {}

        async def fake(self_obj, **kwargs):
            captured.update(kwargs)
            return True

        old = MODULE.orchestrate_index_into_vector_db
        MODULE.orchestrate_index_into_vector_db = fake
        try:
            result = asyncio.run(
                controller.index_into_vector_db(
                    project=SimpleNamespace(project_id=3),
                    chunks=[],
                    chunks_ids=[],
                    do_reset=True,
                )
            )
        finally:
            MODULE.orchestrate_index_into_vector_db = old

        self.assertTrue(result)
        self.assertEqual(captured.get("do_reset"), True)

    def test_style_helper_delegates(self):
        controller = self._controller()
        old = MODULE.orchestrate_infer_answer_style
        MODULE.orchestrate_infer_answer_style = (
            lambda _self, query, explicit_style=None: f"{query}|{explicit_style or ''}"
        )
        try:
            result = controller._infer_answer_style("q", explicit_style="balanced")
        finally:
            MODULE.orchestrate_infer_answer_style = old

        self.assertEqual(result, "q|balanced")

    def test_label_resolution_delegates(self):
        controller = self._controller()
        old = MODULE.orchestrate_resolve_document_label
        MODULE.orchestrate_resolve_document_label = (
            lambda _self, metadata, fallback_label, asset_labels=None, asset_labels_by_name=None, asset_id_hint=None: "DocX"
        )
        try:
            result = controller._resolve_document_label(
                metadata={"asset_id": 1},
                fallback_label="fallback",
            )
        finally:
            MODULE.orchestrate_resolve_document_label = old

        self.assertEqual(result, "DocX")


if __name__ == "__main__":
    unittest.main()
