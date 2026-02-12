import unittest
import asyncio
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

    def generate_text(self, prompt: str, chat_history: list, temperature: float = 0.0) -> str:
        # Intentionally non-JSON to exercise analysis parse-failure fallback.
        return "not-json"


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
class RagAmbiguityTests(unittest.TestCase):
    def test_single_high_confidence_candidate_does_not_require_clarification(self):
        controller = _build_controller()
        analysis = {
            "candidate_answers": [
                {"answer": "1990", "support_count": 3, "confidence": 0.91},
            ],
            "ambiguity_detected": False,
            "answer_confidence": 0.91,
        }
        result = controller._apply_ambiguity_gate(
            analysis=analysis,
            query="When did this happen?",
            ambiguity_threshold=0.12,
            top_n=4,
        )
        self.assertFalse(result["ambiguity_detected"])
        self.assertAlmostEqual(result["answer_confidence"], 0.91, places=3)

    def test_close_conflicting_candidates_require_clarification(self):
        controller = _build_controller()
        analysis = {
            "candidate_answers": [
                {"answer": "1990", "support_count": 2, "confidence": 0.58},
                {"answer": "1991", "support_count": 2, "confidence": 0.53},
                {"answer": "1992", "support_count": 1, "confidence": 0.21},
            ],
            "ambiguity_detected": False,
        }
        result = controller._apply_ambiguity_gate(
            analysis=analysis,
            query="When did this happen?",
            ambiguity_threshold=0.12,
            top_n=4,
        )
        self.assertTrue(result["ambiguity_detected"])
        self.assertTrue(result.get("clarification_question"))
        self.assertTrue(result.get("clarification_options"))

    def test_conflicting_key_values_in_facts_trigger_ambiguity(self):
        controller = _build_controller()
        analysis = {
            "candidate_answers": [
                {"answer": "The event happened in 2020.", "support_count": 1, "confidence": 0.90},
            ],
            "evidence_facts": [
                {"fact": "Document A says the event date is 12/01/2020.", "support": ["Doc A"], "confidence": 0.89},
                {"fact": "Document B says the event date is 15/01/2021.", "support": ["Doc B"], "confidence": 0.88},
            ],
            "ambiguity_detected": False,
        }
        result = controller._apply_ambiguity_gate(
            analysis=analysis,
            query="When did this happen?",
            ambiguity_threshold=0.12,
            top_n=4,
        )
        self.assertTrue(result["ambiguity_detected"])
        reason = str(result.get("ambiguity_reason") or "").lower()
        self.assertIn("conflicting key values", reason)

    def test_analysis_parse_failure_marks_metric_flags(self):
        controller = _build_controller()
        docs = [SimpleNamespace(text="Evidence text", score=0.8, metadata={"chunk_id": 1})]
        result = asyncio.run(
            controller.analyze_evidence_for_answer(
                query="When did this happen?",
                retrieved_documents=docs,
                template_group="rag",
            )
        )
        self.assertEqual(result.get("__analysis_source"), "heuristic")
        self.assertTrue(bool(result.get("__analysis_parse_failed", False)))
        self.assertTrue(isinstance(result.get("evidence_summary"), str))


if __name__ == "__main__":
    unittest.main()
