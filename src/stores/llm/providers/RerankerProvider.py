import logging
from typing import Any, Dict, List, Optional

import httpx


class RerankerProvider:
    """
    Lightweight HTTP client for reranking services. It expects the target API
    to accept a JSON payload that includes the model identifier, query text,
    and a list of documents, and to return a JSON body with either a `results`
    or `data` array. Each array item should contain at least an `index` field
    referencing the original document position plus a numeric score.
    """

    def __init__(
        self,
        api_url: str,
        model_id: str,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.api_url = api_url
        self.model_id = model_id
        self.api_key = api_key
        self.timeout = timeout
        self.logger = logging.getLogger(__name__)

    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_n: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not query or not documents:
            return []

        payload: Dict[str, Any] = {
            "model": self.model_id,
            "query": query,
            "documents": documents,
        }
        if top_n is not None and top_n > 0:
            payload["top_n"] = min(top_n, len(documents))

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            token = self.api_key.strip()
            if not token.lower().startswith("bearer "):
                token = f"Bearer {token}"
            headers["Authorization"] = token

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.api_url, json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()

        entries = body.get("results") or body.get("data") or body.get("documents")
        if not isinstance(entries, list):
            self.logger.warning("Unexpected reranker response format: %s", body)
            return []

        normalized: List[Dict[str, Any]] = []
        for item in entries:
            if not isinstance(item, dict):
                continue
            index = item.get("index")
            if index is None:
                index = item.get("document_index") or item.get("document")
            score = (
                item.get("score")
                or item.get("relevance_score")
                or item.get("relevance")
                or item.get("value")
            )
            try:
                if index is None:
                    continue
                normalized.append(
                    {
                        "index": int(index),
                        "score": float(score) if score is not None else 0.0,
                    }
                )
            except (TypeError, ValueError):
                continue

        return normalized
