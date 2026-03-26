from enum import Enum


class VectorDBEnums(Enum):
    PGVECTOR = "PGVECTOR"


class DistanceMethodEnums(Enum):
    COSINE = "cosine"
    DOT = "dot"

class PgVectorTableSchemeEnums(Enum):
    ID = 'id'
    TEXT = 'text'
    VECTOR = 'vector'
    CHUNK_ID = 'chunk_id'
    METADATA = 'metadata'
    FTS = 'fts'
    _PREFIX = 'collection_'

class PgVectorDistanceMethodEnums(Enum):
    COSINE = "vector_cosine_ops"
    DOT = "vector_ip_ops"

class PgVectorIndexTypeEnums(Enum):
    HNSW = "hnsw"
    IVFFLAT = "ivfflat"
