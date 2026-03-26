import pathlib
import sys
import tempfile
import unittest
import importlib.util
import types
from unittest.mock import patch


SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"
_fake_sentence_transformers = types.ModuleType("sentence_transformers")
_fake_sentence_transformers.CrossEncoder = object

with patch.dict(sys.modules, {"sentence_transformers": _fake_sentence_transformers}):
    _spec = importlib.util.spec_from_file_location(
        "stores.llm.providers.CrossEncoderRerankerProvider",
        SRC_ROOT / "stores" / "llm" / "providers" / "CrossEncoderRerankerProvider.py",
    )
    _module = importlib.util.module_from_spec(_spec)
    assert _spec and _spec.loader
    _spec.loader.exec_module(_module)
    CrossEncoderRerankerProvider = _module.CrossEncoderRerankerProvider


class CrossEncoderRerankerProviderLoadSelectionTests(unittest.TestCase):
    def test_local_directory_model_id_loads_local_path(self):
        with tempfile.TemporaryDirectory() as model_dir:
            with patch.object(_module, "CrossEncoder") as mock_cross_encoder:
                CrossEncoderRerankerProvider(
                    model_id=model_dir,
                    fallback_model_id="cross-encoder/ms-marco-MiniLM-L-6-v2",
                )

        self.assertEqual(mock_cross_encoder.call_count, 1)
        self.assertEqual(mock_cross_encoder.call_args.args[0], model_dir)

    def test_remote_model_id_is_attempted_before_fallback(self):
        primary = "BAAI/bge-reranker-v2-m3"
        fallback = "cross-encoder/ms-marco-MiniLM-L-6-v2"

        with patch.object(
            _module,
            "CrossEncoder",
            side_effect=[RuntimeError("primary failed"), object()],
        ) as mock_cross_encoder:
            CrossEncoderRerankerProvider(
                model_id=primary,
                fallback_model_id=fallback,
            )

        self.assertEqual(mock_cross_encoder.call_count, 2)
        self.assertEqual(mock_cross_encoder.call_args_list[0].args[0], primary)
        self.assertEqual(mock_cross_encoder.call_args_list[1].args[0], fallback)

    def test_raises_when_primary_and_fallback_fail(self):
        with patch.object(
            _module,
            "CrossEncoder",
            side_effect=[RuntimeError("primary failed"), RuntimeError("fallback failed")],
        ):
            with self.assertRaises(RuntimeError):
                CrossEncoderRerankerProvider(
                    model_id="BAAI/bge-reranker-v2-m3",
                    fallback_model_id="cross-encoder/ms-marco-MiniLM-L-6-v2",
                )


if __name__ == "__main__":
    unittest.main()
