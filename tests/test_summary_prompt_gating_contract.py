import pathlib
import unittest


SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"


class SummaryPromptGatingContractTests(unittest.TestCase):
    def test_summary_prompt_payload_is_debug_gated(self):
        content = (
            SRC_ROOT / "routes" / "nlp_summary_orchestrator.py"
        ).read_text(encoding="utf-8")
        self.assertIn("DEBUG_INCLUDE_PROMPTS", content)
        self.assertIn("exposed_full_prompt", content)
        self.assertIn('"full_prompt": payload_prompt', content)
        self.assertIn("prompt_text=stored_prompt", content)


if __name__ == "__main__":
    unittest.main()
