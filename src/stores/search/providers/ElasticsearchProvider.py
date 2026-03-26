import logging
from typing import Any, Dict, List, Optional

import httpx

from ..SearchProviderInterface import SearchProviderInterface


logger = logging.getLogger(__name__)


class ElasticsearchProvider(SearchProviderInterface):
    def __init__(self, base_url: str, index_prefix: str = "minirag"):
        self.base_url = base_url.rstrip("/")
        self.index_prefix = index_prefix
        self._client: Optional[httpx.AsyncClient] = None

    def get_index_name(self, project_id: int) -> str:
        # Single shared index for all projects; scope by project_id field.
        return f"{self.index_prefix}-chunks"

    async def connect(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def index_documents(
        self,
        index_name: str,
        documents: List[Dict[str, Any]],
    ) -> None:
        if not documents:
            return

        await self._ensure_client()
        await self._ensure_index(index_name)

        body_parts: List[str] = []
        for doc in documents:
            index_meta: Dict[str, Any] = {"_index": index_name}
            chunk_id = doc.get("chunk_id")
            project_id = doc.get("project_id")
            if chunk_id is not None and project_id is not None:
                index_meta["_id"] = f"{project_id}:{chunk_id}"

            action = {"index": index_meta}
            body_parts.append(self._json_dumps(action))
            body_parts.append(self._json_dumps(doc))

        body = "\n".join(body_parts) + "\n"

        try:
            assert self._client is not None
            resp = await self._client.post("/_bulk", content=body, headers={"Content-Type": "application/x-ndjson"})
            resp.raise_for_status()
        except Exception as exc:
            logger.error("Failed to bulk index documents into %s: %s", index_name, exc)

    async def search(
        self,
        index_name: str,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        size: int = 10,
    ) -> List[Dict[str, Any]]:
        await self._ensure_client()
        await self._ensure_index(index_name)

        must_clauses: List[Dict[str, Any]] = []
        if query:
            must_clauses.append(
                {
                    "multi_match": {
                        "query": query,
                        "fields": ["text^2", "text.ar", "text.en"],
                    }
                }
            )

        filter_clauses: List[Dict[str, Any]] = []
        if filters:
            for field, value in filters.items():
                if value is None:
                    continue
                filter_clauses.append({"term": {field: value}})

        es_query: Dict[str, Any] = {"bool": {}}
        if must_clauses:
            es_query["bool"]["must"] = must_clauses
        if filter_clauses:
            es_query["bool"]["filter"] = filter_clauses

        payload = {
            "query": es_query,
            "size": size,
        }

        try:
            assert self._client is not None
            resp = await self._client.post(f"/{index_name}/_search", json=payload)
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:
            logger.error("Elasticsearch search failed on %s: %s", index_name, exc)
            return []

        hits = body.get("hits", {}).get("hits", [])
        results: List[Dict[str, Any]] = []
        for hit in hits:
            source = hit.get("_source", {}) or {}
            score = hit.get("_score")
            if score is not None:
                source["_score"] = score
            results.append(source)
        return results

    async def _ensure_client(self) -> None:
        if self._client is None:
            await self.connect()

    async def _ensure_index(self, index_name: str) -> None:
        """
        Ensure the target index exists with a mapping that supports
        mixed Arabic/English text and basic metadata fields.
        """
        assert self._client is not None

        try:
            resp = await self._client.head(f"/{index_name}")
            if resp.status_code == 200:
                return
        except Exception as exc:
            logger.error("Failed to check index %s: %s", index_name, exc)
            return

        settings: Dict[str, Any] = {
            "analysis": {
                "filter": {
                    "arabic_stemmer": {"type": "stemmer", "language": "arabic"},
                    "english_stemmer": {"type": "stemmer", "language": "english"},
                },
                "analyzer": {
                    "arabic_text": {
                        "tokenizer": "standard",
                        "filter": ["lowercase", "arabic_normalization", "arabic_stemmer"],
                    },
                    "english_text": {
                        "tokenizer": "standard",
                        "filter": ["lowercase", "english_stemmer"],
                    },
                    "mixed_ar_en": {
                        "tokenizer": "standard",
                        "filter": [
                            "lowercase",
                            "arabic_normalization",
                            "arabic_stemmer",
                            "english_stemmer",
                        ],
                    },
                },
            }
        }

        mappings: Dict[str, Any] = {
            "properties": {
                "text": {
                    "type": "text",
                    "analyzer": "mixed_ar_en",
                    "fields": {
                        "ar": {"type": "text", "analyzer": "arabic_text"},
                        "en": {"type": "text", "analyzer": "english_text"},
                    },
                },
                "project_id": {"type": "integer"},
                "asset_id": {"type": "integer"},
                "chunk_id": {"type": "integer"},
                "doc_type": {"type": "keyword"},
                "page": {"type": "integer"},
                "page_number": {"type": "integer"},
                "original_filename": {"type": "keyword"},
                "metadata": {"type": "object", "enabled": False},
            }
        }

        body = {"settings": settings, "mappings": mappings}

        try:
            resp = await self._client.put(f"/{index_name}", json=body)
            resp.raise_for_status()
        except Exception as exc:
            logger.error("Failed to create index %s: %s", index_name, exc)

    @staticmethod
    def _json_dumps(data: Dict[str, Any]) -> str:
        # Local import to avoid requiring or configuring a global JSON dependency.
        import json

        return json.dumps(data, ensure_ascii=False)
