import unittest
import pathlib
import sys
import types
import importlib.util
import os

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
class MultiHopAmbiguityTests(unittest.TestCase):
    def test_multihop_conflict_returns_arabic_clarification_prompt_for_ar_query(self):
        controller = _build_controller()
        analysis = {
            "candidate_answers": [
                {"answer": "1990", "support_count": 2, "confidence": 0.55},
                {"answer": "1991", "support_count": 2, "confidence": 0.54},
            ],
            "ambiguity_detected": False,
        }
        result = controller._apply_ambiguity_gate(
            analysis=analysis,
            query="متى بدأ هذا الحدث؟",
            ambiguity_threshold=0.12,
            top_n=4,
        )
        self.assertTrue(result["ambiguity_detected"])
        self.assertTrue(result.get("clarification_question"))
        self.assertIn("هل", result.get("clarification_question"))


if __name__ == "__main__":
    unittest.main()
