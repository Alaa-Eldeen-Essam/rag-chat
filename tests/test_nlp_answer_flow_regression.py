import asyncio
import pathlib
import sys
import unittest
from types import SimpleNamespace

SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.append(str(SRC_ROOT))

from controllers.nlp_answer_flow_orchestrator import answer_rag_question


class _StubController:
    def __init__(self):
        self.called_generate = False
        self.called_direct = False

    def _detect_question_type(self, query: str) -> str:
        return "when"

    def _infer_answer_style(self, query: str, explicit_style=None) -> str:
        return "balanced"

    async def search_vector_db_collection(self, **_kwargs):
        return []

    def _try_extract_direct_answer(self, query, documents, question_type):
        self.called_direct = True
        return None

    def _resolve_document_label(self, metadata, fallback_label, **_kwargs):
        return fallback_label

    def _default_answer_metadata(self):
        return {
            "needs_clarification": False,
            "clarification_question": None,
            "clarification_options": None,
            "answer_confidence": None,
            "ambiguity_reason": None,
            "evidence_summary": None,
        }

    async def generate_rag_answer_from_documents(self, **_kwargs):
        self.called_generate = True
        return "generated", None, None, self._default_answer_metadata()


class AnswerFlowRegressionTests(unittest.TestCase):
    def test_when_direct_hint_short_circuit_returns_deterministic_answer(self):
        controller = _StubController()

        async def fake_search(**_kwargs):
            return [
                SimpleNamespace(
                    text="The event happened on 2 December 2021 according to the record.",
                    metadata={"source_name": "Doc A"},
                )
            ]

        controller.search_vector_db_collection = fake_search
        controller._try_extract_direct_answer = lambda **_kwargs: "2 December 2021"
        controller._resolve_document_label = lambda metadata, fallback_label, **_kwargs: "Doc A"

        result = asyncio.run(
            answer_rag_question(
                controller=controller,
                project=SimpleNamespace(project_id=1),
                query="When did this happen?",
                limit=5,
            )
        )

        self.assertEqual(len(result), 4)
        self.assertIn("According to the document", result[0])
        self.assertIn("2 December 2021", result[0])
        self.assertEqual(result[3].get("answer_confidence"), 1.0)
        self.assertFalse(controller.called_generate)

    def test_arabic_lahn_guardrail_short_circuits_when_no_supporting_chunk(self):
        controller = _StubController()
        query = "\u0645\u062a\u0649 \u0634\u0627\u0639 \u0627\u0644\u0644\u062d\u0646 \u0628\u064a\u0646 \u0627\u0644\u0639\u0631\u0628\u061f"

        async def fake_search(**_kwargs):
            return [SimpleNamespace(text="\u0646\u0635 \u0639\u0627\u0645 \u0628\u062f\u0648\u0646 \u0627\u0644\u0641\u0638 \u0627\u0644\u0644\u062d\u0646", metadata={})]

        controller.search_vector_db_collection = fake_search

        def should_not_call(**_kwargs):
            raise AssertionError("direct-answer extractor should not run on guardrail short-circuit")

        controller._try_extract_direct_answer = should_not_call

        result = asyncio.run(
            answer_rag_question(
                controller=controller,
                project=SimpleNamespace(project_id=1),
                query=query,
            )
        )

        self.assertEqual(len(result), 4)
        self.assertIn("\u0644\u0627 \u064a\u0645\u0643\u0646 \u062a\u062d\u062f\u064a\u062f", result[0])
        self.assertFalse(controller.called_generate)


if __name__ == "__main__":
    unittest.main()
