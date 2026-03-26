import pathlib
import unittest


SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"


class AnswerRouteContractGuardTests(unittest.TestCase):
    def test_answer_route_rejects_unknown_model_and_uses_project_scope(self):
        content = (SRC_ROOT / "routes" / "nlp_answer_orchestrator.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("Unknown model", content)
        self.assertIn("status.HTTP_400_BAD_REQUEST", content)
        self.assertIn("get_all_project_assets(", content)
        self.assertNotIn("get_all_accessible_assets(", content)

    def test_answer_route_keeps_prompt_debug_gating_and_grounding_ratio(self):
        content = (SRC_ROOT / "routes" / "nlp_answer_orchestrator.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def _exposed_full_prompt", content)
        self.assertIn("RAG_GROUNDING_MIN_GROUNDED_CLAIM_RATIO", content)
        self.assertIn("grounded_claim_ratio", content)

    def test_answer_route_uses_canonical_controller_entrypoint(self):
        content = (SRC_ROOT / "routes" / "nlp_answer_orchestrator.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("answer_rag_from_documents(", content)
        self.assertNotIn("generate_rag_answer_from_documents(", content)


if __name__ == "__main__":
    unittest.main()
