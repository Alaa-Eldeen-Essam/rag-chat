import pathlib
import unittest


SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"


class IndexPathPerformanceContractTests(unittest.TestCase):
    def test_index_route_has_no_tqdm_dependency(self):
        content = (SRC_ROOT / "routes" / "nlp_index_orchestrator.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("from tqdm.auto import tqdm", content)
        self.assertIn("INDEX_PROGRESS", content)


if __name__ == "__main__":
    unittest.main()
