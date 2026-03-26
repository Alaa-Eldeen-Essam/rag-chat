import asyncio
import pathlib
import sys
import importlib.util
import unittest
from types import SimpleNamespace


SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.append(str(SRC_ROOT))

_module = None
IMPORT_ERROR = None
try:
    _spec = importlib.util.spec_from_file_location(
        "routes.nlp",
        SRC_ROOT / "routes" / "nlp.py",
    )
    _module = importlib.util.module_from_spec(_spec)
    assert _spec and _spec.loader
    _spec.loader.exec_module(_module)
except Exception as exc:  # pragma: no cover - environment dependent
    _module = None
    IMPORT_ERROR = exc


@unittest.skipIf(_module is None, f"routes.nlp import failed: {IMPORT_ERROR}")
class NlpRouteWrapperTests(unittest.TestCase):
    def test_index_project_wrapper_delegates(self):
        calls = {}

        async def fake_handler(**kwargs):
            calls.update(kwargs)
            return {"ok": True}

        old = _module.handle_index_project
        _module.handle_index_project = fake_handler
        try:
            result = asyncio.run(
                _module.index_project(
                    request="request",
                    project_id=7,
                    push_request="payload",
                    current_user="user",
                )
            )
        finally:
            _module.handle_index_project = old

        self.assertEqual(result, {"ok": True})
        self.assertEqual(calls.get("project_id"), 7)
        self.assertEqual(calls.get("push_request"), "payload")

    def test_conversation_wrapper_delegates(self):
        calls = {}

        async def fake_handler(**kwargs):
            calls.update(kwargs)
            return {"conversation": True}

        old = _module.handle_list_conversations
        _module.handle_list_conversations = fake_handler
        try:
            result = asyncio.run(
                _module.list_conversations(
                    request="request",
                    current_user="user",
                )
            )
        finally:
            _module.handle_list_conversations = old

        self.assertEqual(result, {"conversation": True})
        self.assertEqual(calls.get("current_user"), "user")

    def test_summary_wrapper_passes_language_detector(self):
        calls = {}

        async def fake_handler(**kwargs):
            calls.update(kwargs)
            return {"summary": True}

        old = _module.handle_summarize_project
        _module.handle_summarize_project = fake_handler
        try:
            result = asyncio.run(
                _module.summarize_project(
                    request=SimpleNamespace(),
                    project_id=12,
                    summarize_request="summary-req",
                    current_user="user",
                    app_settings="settings",
                )
            )
        finally:
            _module.handle_summarize_project = old

        self.assertEqual(result, {"summary": True})
        self.assertEqual(calls.get("project_id"), 12)
        self.assertIs(calls.get("language_detector"), _module.detect_language_or_default)

    def test_answer_wrapper_passes_language_detector(self):
        calls = {}

        async def fake_handler(**kwargs):
            calls.update(kwargs)
            return {"answer": True}

        old = _module.handle_answer_rag
        _module.handle_answer_rag = fake_handler
        try:
            result = asyncio.run(
                _module.answer_rag(
                    request="request",
                    project_id=19,
                    search_request="search-req",
                    current_user="user",
                    app_settings="settings",
                )
            )
        finally:
            _module.handle_answer_rag = old

        self.assertEqual(result, {"answer": True})
        self.assertEqual(calls.get("project_id"), 19)
        self.assertIs(calls.get("language_detector"), _module.detect_language_or_default)


if __name__ == "__main__":
    unittest.main()
