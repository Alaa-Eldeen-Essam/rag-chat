from ..VectorDBInterface import VectorDBInterface
from ..VectorDBEnums import (
    DistanceMethodEnums,
    PgVectorTableSchemeEnums,
    PgVectorDistanceMethodEnums,
    PgVectorIndexTypeEnums,
)
import logging
from typing import List, Optional, Any
from models.db_schemes import RetrievedDocument
from sqlalchemy.sql import text as sql_text
import json


class PGVectorProvider(VectorDBInterface):

    def __init__(self, db_client, default_vector_size: int = 786,
                 distance_method: str = None, index_threshold: int = 100):

        self.db_client = db_client
        self.default_vector_size = default_vector_size
        self.index_threshold = index_threshold

        if distance_method == DistanceMethodEnums.COSINE.value:
            distance_method = PgVectorDistanceMethodEnums.COSINE.value
        elif distance_method == DistanceMethodEnums.DOT.value:
            distance_method = PgVectorDistanceMethodEnums.DOT.value

        self.pgvector_table_prefix = PgVectorTableSchemeEnums._PREFIX.value
        self.distance_method = distance_method or PgVectorDistanceMethodEnums.COSINE.value

        self.logger = logging.getLogger("uvicorn")
        self.default_index_name = lambda collection_name: f"{collection_name}_vector_idx"
        self.default_fts_index_name = lambda collection_name: f"{collection_name}_fts_idx"

    async def connect(self):
        async with self.db_client() as session:
            try:
                # Check if vector extension already exists
                result = await session.execute(sql_text(
                    "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
                  ))
                extension_exists = result.scalar_one_or_none()

                if not extension_exists:
                    # Only create if it doesn't exist
                    await session.execute(sql_text("CREATE EXTENSION vector"))
                    await session.commit()
            except Exception as e:
                # If extension already exists or any other error, just log and continue
                self.logger.warning(f"Vector extension setup: {str(e)}")
                await session.rollback()
    async def disconnect(self):
        return

    async def is_collection_existed(self, collection_name: str) -> bool:
        async with self.db_client() as session:
            async with session.begin():
                stmt = sql_text(
                    "SELECT 1 FROM pg_tables WHERE tablename = :collection_name"
                )
                result = await session.execute(stmt, {"collection_name": collection_name})
                return result.scalar_one_or_none() is not None

    async def list_all_collections(self) -> List:
        async with self.db_client() as session:
            async with session.begin():
                stmt = sql_text(
                    'SELECT tablename FROM pg_tables WHERE tablename LIKE :prefix'
                )
                result = await session.execute(
                    stmt, {"prefix": f"{self.pgvector_table_prefix}%"}
                )
                return result.scalars().all()

    async def get_collection_info(self, collection_name: str) -> Optional[dict]:
        async with self.db_client() as session:
            async with session.begin():
                table_info_sql = sql_text(
                    """
                        SELECT schemaname, tablename, tableowner, tablespace, hasindexes
                        FROM pg_tables
                        WHERE tablename = :collection_name
                    """
                )
                count_sql = sql_text(f'SELECT COUNT(*) FROM {collection_name}')

                table_info = await session.execute(
                    table_info_sql, {"collection_name": collection_name}
                )
                record_count = await session.execute(count_sql)

                table_data = table_info.fetchone()
                if not table_data:
                    return None

                return {
                    "table_info": {
                        "schemaname": table_data[0],
                        "tablename": table_data[1],
                        "tableowner": table_data[2],
                        "tablespace": table_data[3],
                        "hasindexes": table_data[4],
                    },
                    "record_count": record_count.scalar_one(),
                }

    async def delete_collection(self, collection_name: str):
        async with self.db_client() as session:
            async with session.begin():
                self.logger.info("Deleting collection: %s", collection_name)
                delete_sql = sql_text(f'DROP TABLE IF EXISTS {collection_name}')
                await session.execute(delete_sql)
                await session.commit()
        return True

    async def create_collection(self, collection_name: str,
                                embedding_size: int,
                                do_reset: bool = False):

        if do_reset:
            await self.delete_collection(collection_name=collection_name)

        collection_exists = await self.is_collection_existed(collection_name=collection_name)

        if not collection_exists:
            self.logger.info("Creating collection: %s", collection_name)
            async with self.db_client() as session:
                async with session.begin():
                    create_sql = sql_text(
                        f'CREATE TABLE {collection_name} ('
                        f'{PgVectorTableSchemeEnums.ID.value} bigserial PRIMARY KEY,'
                        f'{PgVectorTableSchemeEnums.TEXT.value} text NOT NULL, '
                        f'{PgVectorTableSchemeEnums.VECTOR.value} vector({embedding_size}) NOT NULL, '
                        f"{PgVectorTableSchemeEnums.METADATA.value} jsonb DEFAULT '{{}}'::jsonb, "
                        f'{PgVectorTableSchemeEnums.CHUNK_ID.value} integer NOT NULL, '
                        f'FOREIGN KEY ({PgVectorTableSchemeEnums.CHUNK_ID.value}) '
                        f'REFERENCES chunks(chunk_id) ON DELETE CASCADE'
                        ')'
                    )
                    await session.execute(create_sql)
                    await session.commit()

        # Lexical search is now handled primarily by Elasticsearch. We no longer
        # create or maintain a Postgres FTS column/index eagerly here; FTS
        # support is only enabled on-demand when search_by_text is used as a
        # fallback in environments without Elasticsearch.
        return True

    async def ensure_text_search_support(self, collection_name: str) -> None:
        """Ensure each collection has a tsvector column + GIN index for lexical search."""
        async with self.db_client() as session:
            async with session.begin():
                try:
                    alter_sql = sql_text(
                        f"""
                        ALTER TABLE {collection_name}
                        ADD COLUMN IF NOT EXISTS {PgVectorTableSchemeEnums.FTS.value} tsvector
                        GENERATED ALWAYS AS (
                            to_tsvector('simple', COALESCE({PgVectorTableSchemeEnums.TEXT.value}, ''))
                        ) STORED
                        """
                    )
                    await session.execute(alter_sql)
                except Exception as exc:
                    self.logger.error(
                        "Failed to ensure FTS column on %s: %s", collection_name, exc
                    )
                    raise

                create_idx_sql = sql_text(
                    f"""
                    CREATE INDEX IF NOT EXISTS {self.default_fts_index_name(collection_name)}
                    ON {collection_name} USING GIN ({PgVectorTableSchemeEnums.FTS.value})
                    """
                )
                await session.execute(create_idx_sql)

    async def is_index_existed(self, collection_name: str) -> bool:
        index_name = self.default_index_name(collection_name)
        async with self.db_client() as session:
            async with session.begin():
                check_sql = sql_text(
                    """
                        SELECT 1
                        FROM pg_indexes
                        WHERE tablename = :collection_name
                        AND indexname = :index_name
                    """
                )
                results = await session.execute(
                    check_sql,
                    {"index_name": index_name, "collection_name": collection_name},
                )
                return results.scalar_one_or_none() is not None

    async def create_vector_index(self, collection_name: str,
                                  index_type: str = PgVectorIndexTypeEnums.HNSW.value):
        if await self.is_index_existed(collection_name):
            return False

        async with self.db_client() as session:
            async with session.begin():
                count_sql = sql_text(f'SELECT COUNT(*) FROM {collection_name}')
                result = await session.execute(count_sql)
                records_count = result.scalar_one()

                if records_count < self.index_threshold:
                    return False

                self.logger.info("START: Creating vector index for %s", collection_name)

                # Determine effective index type. HNSW in pgvector has a hard limit
                # of 2000 dimensions; for larger embeddings (e.g., 2560-dim models
                # like Qwen3 Embedding 4B), fall back to IVFFLAT automatically.
                effective_index_type = index_type
                embedding_dim = None
                try:
                    # collection naming convention: collection_{dim}_{project_id}
                    parts = collection_name.split("_")
                    if len(parts) >= 3:
                        embedding_dim = int(parts[1])
                except Exception:
                    embedding_dim = None

                if embedding_dim is None:
                    embedding_dim = self.default_vector_size

                if (
                    embedding_dim is not None
                    and embedding_dim > 2000
                    and effective_index_type == PgVectorIndexTypeEnums.HNSW.value
                ):
                    self.logger.info(
                        "Embedding dimension %s exceeds HNSW limit; "
                        "using IVFFLAT index for %s instead of HNSW",
                        embedding_dim,
                        collection_name,
                    )
                    effective_index_type = PgVectorIndexTypeEnums.IVFFLAT.value

                index_name = self.default_index_name(collection_name)
                try:
                    create_idx_sql = sql_text(
                        f'CREATE INDEX {index_name} ON {collection_name} '
                        f'USING {effective_index_type} '
                        f'({PgVectorTableSchemeEnums.VECTOR.value} {self.distance_method})'
                    )
                    await session.execute(create_idx_sql)
                except Exception as exc:
                    self.logger.error(
                        "Failed to create vector index %s on %s: %s",
                        index_name,
                        collection_name,
                        exc,
                    )
                    return False

                self.logger.info("END: Created vector index for %s", collection_name)

        return True

    async def reset_vector_index(self, collection_name: str,
                                 index_type: str = PgVectorIndexTypeEnums.HNSW.value) -> bool:
        index_name = self.default_index_name(collection_name)
        async with self.db_client() as session:
            async with session.begin():
                drop_sql = sql_text(f'DROP INDEX IF EXISTS {index_name}')
                await session.execute(drop_sql)
        return await self.create_vector_index(collection_name, index_type=index_type)

    async def insert_one(self, collection_name: str, text: str, vector: list,
                         metadata: dict = None,
                         record_id: Optional[int] = None):

        if not await self.is_collection_existed(collection_name):
            self.logger.error("Can not insert into non-existent collection: %s", collection_name)
            return False

        if not record_id:
            self.logger.error("chunk_id is required when inserting into %s", collection_name)
            return False

        payload_metadata = metadata if metadata is not None else {}
        async with self.db_client() as session:
            async with session.begin():
                insert_sql = sql_text(
                    f'INSERT INTO {collection_name} '
                    f'({PgVectorTableSchemeEnums.TEXT.value}, '
                    f'{PgVectorTableSchemeEnums.VECTOR.value}, '
                    f'{PgVectorTableSchemeEnums.METADATA.value}, '
                    f'{PgVectorTableSchemeEnums.CHUNK_ID.value}) '
                    'VALUES (:text, :vector, :metadata, :chunk_id)'
                )
                await session.execute(
                    insert_sql,
                    {
                        'text': text,
                        'vector': "[" + ",".join([str(v) for v in vector]) + "]",
                        'metadata': json.dumps(payload_metadata, ensure_ascii=False),
                        'chunk_id': record_id,
                    },
                )
                await session.commit()

        await self.create_vector_index(collection_name)
        return True

    async def insert_many(self, collection_name: str, texts: list,
                          vectors: list, metadata: list = None,
                          record_ids: list = None, batch_size: int = 50):

        if not await self.is_collection_existed(collection_name):
            self.logger.error("Can not insert into non-existent collection: %s", collection_name)
            return False

        if record_ids is None or len(vectors) != len(record_ids):
            self.logger.error("Invalid record_ids for collection: %s", collection_name)
            return False

        if not metadata or len(metadata) == 0:
            metadata = [None] * len(texts)

        async with self.db_client() as session:
            async with session.begin():
                for i in range(0, len(texts), batch_size):
                    batch_texts = texts[i:i + batch_size]
                    batch_vectors = vectors[i:i + batch_size]
                    batch_metadata = metadata[i:i + batch_size]
                    batch_record_ids = record_ids[i:i + batch_size]

                    values = []
                    for _text, _vector, _metadata, _record_id in zip(
                        batch_texts, batch_vectors, batch_metadata, batch_record_ids
                    ):
                        metadata_payload = _metadata if _metadata is not None else {}
                        values.append(
                            {
                                'text': _text,
                                'vector': "[" + ",".join([str(v) for v in _vector]) + "]",
                                'metadata': json.dumps(metadata_payload, ensure_ascii=False),
                                'chunk_id': _record_id,
                            }
                        )

                    batch_insert_sql = sql_text(
                        f'INSERT INTO {collection_name} '
                        f'({PgVectorTableSchemeEnums.TEXT.value}, '
                        f'{PgVectorTableSchemeEnums.VECTOR.value}, '
                        f'{PgVectorTableSchemeEnums.METADATA.value}, '
                        f'{PgVectorTableSchemeEnums.CHUNK_ID.value}) '
                        f'VALUES (:text, :vector, :metadata, :chunk_id)'
                    )
                    await session.execute(batch_insert_sql, values)

                await session.commit()

        await self.create_vector_index(collection_name)
        return True

    async def search_by_vector(self, collection_name: str, vector: list, limit: int):

        if not await self.is_collection_existed(collection_name):
            self.logger.error("Can not search non-existent collection: %s", collection_name)
            return False

        vector_literal = "[" + ",".join([str(v) for v in vector]) + "]"
        if self.distance_method == PgVectorDistanceMethodEnums.DOT.value:
            score_expr = (
                f'1 / (1 + ({PgVectorTableSchemeEnums.VECTOR.value} <=> :vector))'
            )
        else:
            score_expr = (
                f'1 - ({PgVectorTableSchemeEnums.VECTOR.value} <=> :vector)'
            )

        async with self.db_client() as session:
            async with session.begin():
                search_sql = sql_text(
                    f'SELECT '
                    f'{PgVectorTableSchemeEnums.TEXT.value} AS text, '
                    f'{score_expr} AS score, '
                    f'{PgVectorTableSchemeEnums.METADATA.value} AS metadata, '
                    f'{PgVectorTableSchemeEnums.CHUNK_ID.value} AS chunk_id '
                    f'FROM {collection_name} '
                    'ORDER BY score DESC '
                    'LIMIT :limit'
                )
                result = await session.execute(
                    search_sql, {"vector": vector_literal, "limit": limit}
                )
                records = result.fetchall()

        documents: List[RetrievedDocument] = []
        for record in records:
            metadata_value: Optional[Any] = getattr(record, "metadata", None)
            if isinstance(metadata_value, str):
                try:
                    metadata_value = json.loads(metadata_value)
                except json.JSONDecodeError:
                    metadata_value = None
            chunk_id_value = getattr(record, "chunk_id", None)
            if chunk_id_value is not None:
                if isinstance(metadata_value, dict):
                    metadata_value = {**metadata_value, "chunk_id": chunk_id_value}
                else:
                    metadata_value = {"chunk_id": chunk_id_value}
            documents.append(
                RetrievedDocument(
                    text=record.text,
                    score=float(record.score) if record.score is not None else 0.0,
                    metadata=metadata_value if isinstance(metadata_value, dict) else None,
                )
            )

        return documents

    async def search_by_text(self, collection_name: str, query: str, limit: int):
        if not query:
            return []

        if not await self.is_collection_existed(collection_name):
            self.logger.error("Can not search non-existent collection: %s", collection_name)
            return []

        await self.ensure_text_search_support(collection_name)

        async with self.db_client() as session:
            async with session.begin():
                search_sql = sql_text(
                    f"""
                    SELECT
                        {PgVectorTableSchemeEnums.TEXT.value} AS text,
                        ts_rank_cd({PgVectorTableSchemeEnums.FTS.value}, websearch_to_tsquery(:query)) AS score,
                        {PgVectorTableSchemeEnums.METADATA.value} AS metadata,
                        {PgVectorTableSchemeEnums.CHUNK_ID.value} AS chunk_id
                    FROM {collection_name}
                    WHERE {PgVectorTableSchemeEnums.FTS.value} @@ websearch_to_tsquery(:query)
                    ORDER BY score DESC
                    LIMIT :limit
                    """
                )
                result = await session.execute(
                    search_sql, {"query": query, "limit": limit}
                )
                records = result.fetchall()

        documents: List[RetrievedDocument] = []
        for record in records:
            metadata_value: Optional[Any] = getattr(record, "metadata", None)
            if isinstance(metadata_value, str):
                try:
                    metadata_value = json.loads(metadata_value)
                except json.JSONDecodeError:
                    metadata_value = None
            chunk_id_value = getattr(record, "chunk_id", None)
            if chunk_id_value is not None:
                if isinstance(metadata_value, dict):
                    metadata_value = {**metadata_value, "chunk_id": chunk_id_value}
                else:
                    metadata_value = {"chunk_id": chunk_id_value}
            documents.append(
                RetrievedDocument(
                    text=record.text,
                    score=float(record.score) if record.score is not None else 0.0,
                    metadata=metadata_value if isinstance(metadata_value, dict) else None,
                )
            )

        return documents

    async def delete_records(self, collection_name: str, record_ids: List[int]) -> bool:
        if not record_ids:
            return True

        if not await self.is_collection_existed(collection_name):
            return False

        async with self.db_client() as session:
            async with session.begin():
                delete_sql = sql_text(
                    f'DELETE FROM {collection_name} '
                    f'WHERE {PgVectorTableSchemeEnums.CHUNK_ID.value} = ANY(:chunk_ids)'
                )
                await session.execute(delete_sql, {"chunk_ids": record_ids})
                await session.commit()

        return True

    async def delete_records(self, collection_name: str, record_ids: List[int]) -> bool:
        if not record_ids:
            return True

        if not await self.is_collection_existed(collection_name):
            return False

        async with self.db_client() as session:
            async with session.begin():
                delete_sql = sql_text(
                    f'DELETE FROM {collection_name} '
                    f'WHERE {PgVectorTableSchemeEnums.CHUNK_ID.value} = ANY(:chunk_ids)'
                )
                await session.execute(delete_sql, {"chunk_ids": record_ids})
                await session.commit()

        return True
