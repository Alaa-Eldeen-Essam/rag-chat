import unittest
import pathlib
import sys
import types
import importlib.util
import os
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


class _EnumValue:
    def __init__(self, value: str):
        self.value = value


_DummyGenerationClient.enums.SYSTEM = _EnumValue("system")
_DummyGenerationClient.enums.USER = _EnumValue("user")
_DummyGenerationClient.enums.ASSISTANT = _EnumValue("assistant")


class _DummyTemplateParser:
    def get(self, group: str, key: str, vars: dict | None = None):
        return None


def _build_controller() -> NLPController:
    return NLPController(
        vectordb_client=object(),
        generation_client=_DummyGenerationClient(),
        embedding_client=object(),
        template_parser=_DummyTemplateParser(),
    )


@unittest.skipIf(NLPController is None, f"NLPController import failed: {IMPORT_ERROR}")
class RagHistoryWeightingTests(unittest.TestCase):
    def test_adaptive_history_weight_is_high_for_followups(self):
        controller = _build_controller()
        weight = controller.compute_adaptive_history_weight(
            configured_weight=0.75,
            followup_similarity=0.62,
            followup_threshold=0.30,
        )
        self.assertAlmostEqual(weight, 0.75, places=3)

    def test_adaptive_history_weight_drops_for_topic_shift(self):
        controller = _build_controller()
        weight = controller.compute_adaptive_history_weight(
            configured_weight=0.75,
            followup_similarity=0.08,
            followup_threshold=0.30,
        )
        self.assertLessEqual(weight, 0.35)

    def test_fuse_query_and_history_results(self):
        controller = _build_controller()
        query_docs = [
            SimpleNamespace(text="q1", score=0.95, metadata={"chunk_id": 1}),
            SimpleNamespace(text="q2", score=0.60, metadata={"chunk_id": 2}),
        ]
        history_docs = [
            SimpleNamespace(text="h2", score=0.99, metadata={"chunk_id": 2}),
            SimpleNamespace(text="h3", score=0.75, metadata={"chunk_id": 3}),
        ]
        fused = controller.fuse_query_and_history_results(
            query_only_docs=query_docs,
            history_aware_docs=history_docs,
            limit=3,
            history_weight=0.75,
        )
        self.assertEqual(len(fused), 3)
        # With high history weight, chunk_id=2 should stay near the top.
        top_ids = [int((doc.metadata or {}).get("chunk_id")) for doc in fused[:2]]
        self.assertIn(2, top_ids)

    def test_response_metrics_rates_are_tracked(self):
        controller = _build_controller()
        snap1 = controller.record_response_metrics(
            mode="rag",
            needs_clarification=True,
            parse_failed=False,
        )
        self.assertEqual(int(snap1["mode_total"]), 1)
        self.assertAlmostEqual(float(snap1["mode_clarification_rate"]), 1.0, places=3)
        self.assertAlmostEqual(float(snap1["mode_parse_failure_rate"]), 0.0, places=3)

        snap2 = controller.record_response_metrics(
            mode="rag",
            needs_clarification=False,
            parse_failed=True,
        )
        self.assertEqual(int(snap2["mode_total"]), 2)
        self.assertAlmostEqual(float(snap2["mode_clarification_rate"]), 0.5, places=3)
        self.assertAlmostEqual(float(snap2["mode_parse_failure_rate"]), 0.5, places=3)


if __name__ == "__main__":
    unittest.main()
