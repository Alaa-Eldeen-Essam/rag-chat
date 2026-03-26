import pathlib
import unittest


SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"


class ConversationSignalContractTests(unittest.TestCase):
    def test_conversation_responses_include_detail_code(self):
        content = (
            SRC_ROOT / "routes" / "nlp_conversation_orchestrator.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"detail_code": "conversation_not_found"', content)
        self.assertIn('"detail_code": "conversation_delete_success"', content)
        self.assertIn('"detail_code": "conversation_history_success"', content)


if __name__ == "__main__":
    unittest.main()
