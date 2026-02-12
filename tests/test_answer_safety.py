import pathlib
import sys
import unittest
from types import SimpleNamespace


SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.append(str(SRC_ROOT))

from helpers.answer_safety import (
    build_when_direct_answer,
    has_lahn_arab_support,
    is_direct_hint_supported,
)


class AnswerSafetyTests(unittest.TestCase):
    def test_lahn_support_detection(self):
        docs = [SimpleNamespace(text="انتشر اللحن بين العرب في فترة معينة.")]
        self.assertTrue(has_lahn_arab_support(docs))

    def test_lahn_support_detection_negative(self):
        docs = [SimpleNamespace(text="هذا نص عربي عام.")]
        self.assertFalse(has_lahn_arab_support(docs))

    def test_direct_hint_requires_evidence_support(self):
        docs = [SimpleNamespace(text="The event happened in 2021 in Cairo.")]
        self.assertTrue(
            is_direct_hint_supported(
                query="When did the event happen in Cairo?",
                direct_hint="2021",
                documents=docs,
            )
        )

    def test_direct_hint_rejected_when_missing_from_docs(self):
        docs = [SimpleNamespace(text="The event happened in Cairo.")]
        self.assertFalse(
            is_direct_hint_supported(
                query="When did the event happen in Cairo?",
                direct_hint="2021",
                documents=docs,
            )
        )

    def test_build_when_direct_answer_includes_label(self):
        answer = build_when_direct_answer(
            query="When did it happen?",
            direct_hint="2 December 2021",
            doc_label_for_hint="Doc A",
        )
        self.assertIn("According to the document", answer)
        self.assertIn("2 December 2021", answer)


if __name__ == "__main__":
    unittest.main()
