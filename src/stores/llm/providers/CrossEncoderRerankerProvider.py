import logging
import os
from typing import Any, Dict, List, Optional

import asyncio
from sentence_transformers import CrossEncoder


class CrossEncoderRerankerProvider:
    """
    Local cross-encoder reranker using sentence-transformers.
    Scores (query, doc) pairs and returns ranked indices.
    """

    def __init__(
        self,
        model_id: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        fallback_model_id: Optional[str] = None,
        max_length: int = 512,
        device: Optional[str] = None,
    ):
        self.logger = logging.getLogger(__name__)
        self.model_id = model_id
        self.fallback_model_id = fallback_model_id or model_id

        load_id = model_id
        # If a local path is provided but missing, fall back to the remote id.
        if model_id and os.path.isdir(model_id):
            load_id = model_id
        else:
            load_id = self.fallback_model_id

        try:
            self.model = CrossEncoder(load_id, max_length=max_length, device=device)
        except Exception as exc:
            # If primary load failed and fallback differs, try once more.
            if self.fallback_model_id and load_id != self.fallback_model_id:
                self.logger.warning(
                    "Failed to load cross-encoder %s: %s. Trying fallback %s",
                    load_id,
                    exc,
                    self.fallback_model_id,
                )
                self.model = CrossEncoder(
                    self.fallback_model_id, max_length=max_length, device=device
                )
            else:
                raise

    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_n: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not query or not documents:
            return []

        # Prepare pairs
        pairs = [[query, doc] for doc in documents]

        def _score():
            return self.model.predict(pairs)

        scores = await asyncio.to_thread(_score)
        scored = list(enumerate(scores))
        scored.sort(key=lambda x: x[1], reverse=True)

        limit = top_n if top_n and top_n > 0 else len(scored)
        limit = min(limit, len(scored))

        results: List[Dict[str, Any]] = []
        for idx, score in scored[:limit]:
            try:
                results.append({"index": int(idx), "score": float(score)})
            except Exception:
                continue

        return results
