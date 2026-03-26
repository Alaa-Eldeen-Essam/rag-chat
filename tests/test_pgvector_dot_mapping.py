import importlib.util
import os
import pathlib
import sys
import types
import unittest


SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.append(str(SRC_ROOT))

os.environ.setdefault("APP_NAME", "test")
os.environ.setdefault("APP_VERSION", "0.1")
os.environ.setdefault("FILE_ALLOWED_TYPES", "[\"application/pdf\"]")
os.environ.setdefault("FILE_MAX_SIZE", "10")
os.environ.setdefault("FILE_DEFAULT_CHUNK_SIZE", "1024")
os.environ.setdefault("POSTGRES_USERNAME", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_MAIN_DATABASE", "test")
os.environ.setdefault("GENERATION_BACKEND", "OPENAI")
os.environ.setdefault("EMBEDDING_BACKEND", "OPENAI")
os.environ.setdefault("VECTOR_DB_BACKEND", "PGVECTOR")

if "models.db_schemes" not in sys.modules:
    db_schemes_stub = types.ModuleType("models.db_schemes")

    class RetrievedDocument:  # pragma: no cover - test stub
        pass

    db_schemes_stub.RetrievedDocument = RetrievedDocument
    sys.modules["models.db_schemes"] = db_schemes_stub

vector_enums_spec = importlib.util.spec_from_file_location(
    "stores.vectordb.VectorDBEnums",
    SRC_ROOT / "stores" / "vectordb" / "VectorDBEnums.py",
)
vector_enums_module = importlib.util.module_from_spec(vector_enums_spec)
assert vector_enums_spec and vector_enums_spec.loader
vector_enums_spec.loader.exec_module(vector_enums_module)

provider_spec = importlib.util.spec_from_file_location(
    "stores.vectordb.providers.PGVectorProvider",
    SRC_ROOT / "stores" / "vectordb" / "providers" / "PGVectorProvider.py",
)
provider_module = None
IMPORT_ERROR = None
try:
    provider_module = importlib.util.module_from_spec(provider_spec)
    assert provider_spec and provider_spec.loader
    provider_spec.loader.exec_module(provider_module)
except Exception as exc:  # pragma: no cover - env dependent
    provider_module = None
    IMPORT_ERROR = exc

DistanceMethodEnums = vector_enums_module.DistanceMethodEnums
PgVectorDistanceMethodEnums = vector_enums_module.PgVectorDistanceMethodEnums
PGVectorProvider = provider_module.PGVectorProvider if provider_module is not None else None


@unittest.skipIf(PGVectorProvider is None, f"PGVectorProvider import failed: {IMPORT_ERROR}")
class PGVectorDotMappingTests(unittest.TestCase):
    def test_dot_enum_maps_to_inner_product_ops(self):
        self.assertEqual(PgVectorDistanceMethodEnums.DOT.value, "vector_ip_ops")

    def test_provider_uses_inner_product_score_expression_for_dot(self):
        provider = PGVectorProvider(
            db_client=object(),
            default_vector_size=768,
            distance_method=DistanceMethodEnums.DOT.value,
        )
        self.assertEqual(provider.distance_method, PgVectorDistanceMethodEnums.DOT.value)
        score_expr = provider._build_score_expression()
        self.assertIn("<#>", score_expr)

    def test_provider_uses_cosine_score_expression_for_cosine(self):
        provider = PGVectorProvider(
            db_client=object(),
            default_vector_size=768,
            distance_method=DistanceMethodEnums.COSINE.value,
        )
        score_expr = provider._build_score_expression()
        self.assertIn("<=>", score_expr)


if __name__ == "__main__":
    unittest.main()
