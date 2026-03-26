import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class EnvExamplesRerankerDefaultsTests(unittest.TestCase):
    def test_src_env_example_uses_cross_encoder_defaults_only(self):
        content = (ROOT / "src" / ".env.example").read_text(encoding="utf-8")
        self.assertIn('RERANKER_BACKEND="cross_encoder"', content)
        self.assertIn('RERANKER_MODEL_ID="BAAI/bge-reranker-v2-m3"', content)
        self.assertIn(
            'RERANKER_FALLBACK_MODEL_ID="cross-encoder/ms-marco-MiniLM-L-6-v2"',
            content,
        )
        self.assertNotIn("OLLAMA_RERANKER_", content)
        self.assertNotIn("RERANKER_API_URL", content)
        self.assertNotIn("RERANKER_API_KEY", content)

    def test_docker_env_app_uses_cross_encoder_defaults_only(self):
        content = (ROOT / "docker" / "env" / ".env.app").read_text(encoding="utf-8")
        self.assertIn("RERANKER_ENABLED=true", content)
        self.assertIn('RERANKER_BACKEND="cross_encoder"', content)
        self.assertIn('RERANKER_MODEL_ID="BAAI/bge-reranker-v2-m3"', content)
        self.assertIn(
            'RERANKER_FALLBACK_MODEL_ID="cross-encoder/ms-marco-MiniLM-L-6-v2"',
            content,
        )
        self.assertNotIn("OLLAMA_RERANKER_", content)
        self.assertNotIn("RERANKER_API_URL", content)
        self.assertNotIn("RERANKER_API_KEY", content)


if __name__ == "__main__":
    unittest.main()
