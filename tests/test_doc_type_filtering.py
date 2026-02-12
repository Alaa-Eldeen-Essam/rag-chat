import asyncio
import importlib.util
import pathlib
import sys
import types
import unittest
from types import SimpleNamespace


SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.append(str(SRC_ROOT))

_original_db_schemes = sys.modules.get("models.db_schemes")
_db_schemes_stub = types.ModuleType("models.db_schemes")


class _RetrievedDocumentStub:  # pragma: no cover - import-time stub
    pass


_db_schemes_stub.RetrievedDocument = _RetrievedDocumentStub
sys.modules["models.db_schemes"] = _db_schemes_stub
try:
    _spec = importlib.util.spec_from_file_location(
        "controllers.nlp_retrieval_orchestrator",
        SRC_ROOT / "controllers" / "nlp_retrieval_orchestrator.py",
    )
    _module = importlib.util.module_from_spec(_spec)
    assert _spec and _spec.loader
    _spec.loader.exec_module(_module)
    search_vector_db_collection = _module.search_vector_db_collection
finally:
    if _original_db_schemes is not None:
        sys.modules["models.db_schemes"] = _original_db_schemes
    else:
        sys.modules.pop("models.db_schemes", None)


class _EmbeddingClient:
    def embed_text(self, text, document_type=None):
        return [[0.1, 0.2]]


class _VectorClient:
    async def search_by_vector(self, collection_name, vector, limit):
        return [
            SimpleNamespace(
                text="Military memo",
                score=0.9,
                metadata={"doc_type": "military", "asset_id": 1},
            ),
            SimpleNamespace(
                text="Untyped memo",
                score=0.8,
                metadata={"asset_id": 2},
            ),
        ]

    async def search_by_text(self, collection_name, query, limit):
        return []


class _Controller:
    def __init__(self, strict_doc_type_filter: bool):
        self.embedding_client = _EmbeddingClient()
        self.vectordb_client = _VectorClient()
        self.search_client = None
        self.app_settings = SimpleNamespace(
            RETRIEVAL_DENSE_WEIGHT=0.6,
            RAG_STRICT_DOC_TYPE_FILTER=strict_doc_type_filter,
        )

    def create_collection_name(self, project_id):
        return f"project_{project_id}"

    def _coerce_metadata_dict(self, metadata):
        return metadata if isinstance(metadata, dict) else None


class DocTypeFilteringTests(unittest.TestCase):
    def test_strict_doc_type_filter_excludes_untyped_records(self):
        controller = _Controller(strict_doc_type_filter=True)
        result = asyncio.run(
            search_vector_db_collection(
                controller=controller,
                project=SimpleNamespace(project_id=1),
                text="military update",
                limit=5,
                doc_types=["military"],
            )
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].metadata.get("doc_type"), "military")

    def test_non_strict_doc_type_filter_keeps_untyped_records(self):
        controller = _Controller(strict_doc_type_filter=False)
        result = asyncio.run(
            search_vector_db_collection(
                controller=controller,
                project=SimpleNamespace(project_id=1),
                text="military update",
                limit=5,
                doc_types=["military"],
            )
        )
        self.assertEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()
