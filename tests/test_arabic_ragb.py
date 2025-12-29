import os
import unittest

from scripts.arabic_ragb_eval import run_benchmark


@unittest.skipUnless(
    os.getenv("ARABIC_RAGB_RUN") == "1",
    "Set ARABIC_RAGB_RUN=1 to run ArabicRAGB benchmark locally.",
)
class ArabicRAGBBenchmarkTest(unittest.TestCase):
    def test_arabic_ragb_benchmark(self) -> None:
        base_url = os.getenv("RAG_BENCH_BASE_URL", "http://localhost:5000")
        doc_type = os.getenv("ARABIC_RAGB_DOC_TYPE", "arabic_ragb")
        limit = int(os.getenv("ARABIC_RAGB_LIMIT", "10"))
        top_k = int(os.getenv("ARABIC_RAGB_TOP_K", "5"))
        build_index_flag = os.getenv("ARABIC_RAGB_BUILD_INDEX", "0") == "1"

        results = run_benchmark(
            dataset_name=os.getenv("ARABIC_RAGB_DATASET", "HeshamHaroon/ArabicRAGB"),
            split=os.getenv("ARABIC_RAGB_SPLIT", "train"),
            limit=limit,
            seed=int(os.getenv("ARABIC_RAGB_SEED", "42")),
            base_url=base_url,
            project_id=None,
            doc_type=doc_type,
            top_k=top_k,
            eval_mode="both",
            build_index_flag=build_index_flag,
            max_contexts=int(os.getenv("ARABIC_RAGB_MAX_CONTEXTS", "0")),
            batch_size=int(os.getenv("ARABIC_RAGB_BATCH_SIZE", "10")),
            overlap_threshold=float(os.getenv("ARABIC_RAGB_OVERLAP", "0.2")),
            bypass_header=os.getenv("RAG_BENCH_GUARD_HEADER", "X-Bypass-Prompt-Guard"),
            bypass_value="true" if os.getenv("ARABIC_RAGB_BYPASS_GUARD") == "1" else None,
            token=os.getenv("RAG_BENCH_AUTH_TOKEN", ""),
            basic_user=os.getenv("RAG_BENCH_BASIC_USER", ""),
            basic_pass=os.getenv("RAG_BENCH_BASIC_PASS", ""),
        )

        min_recall = float(os.getenv("ARABIC_RAGB_MIN_RECALL", "0.05"))
        min_f1 = float(os.getenv("ARABIC_RAGB_MIN_F1", "0.05"))

        retrieval = results.get("retrieval") or {}
        generation = results.get("generation") or {}

        self.assertGreaterEqual(
            retrieval.get("overlap_recall_at_k", 0.0),
            min_recall,
            f"Overlap Recall@{top_k} below threshold",
        )
        self.assertGreaterEqual(
            generation.get("token_f1", 0.0),
            min_f1,
            "Token F1 below threshold",
        )


if __name__ == "__main__":
    unittest.main()
