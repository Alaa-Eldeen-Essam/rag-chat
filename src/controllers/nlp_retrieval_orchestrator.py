import logging
import re
import time
from typing import Any, Dict, List, Optional

from models.db_schemes import RetrievedDocument
from stores.llm.LLMEnums import DocumentTypeEnum

logger = logging.getLogger(__name__)


def build_lexical_query(text: str) -> str:
    if not text:
        return ""

    raw = (text or "").strip()
    parts = [p.strip() for p in re.split(r"[\r\n]+", raw) if p.strip()]
    if parts:
        raw = parts[-1]

    lowered = raw.lower()

    ar_stop = {
        "\u0645\u062a\u0649",
        "\u0644\u0645\u0627\u0630\u0627",
        "\u0644\u064a\u0647",
        "\u0644\u064a\u0634",
        "\u0647\u0644",
        "\u0645\u0627",
        "\u0645\u0627\u0630\u0627",
        "\u0643\u0645",
        "\u0645\u0646",
        "\u0623\u064a\u0646",
        "\u0627\u064a\u0646",
        "\u0643\u064a\u0641",
    }
    en_stop = {
        "when",
        "why",
        "what",
        "who",
        "where",
        "how",
        "is",
        "are",
        "do",
        "does",
        "did",
    }

    tokens = re.findall(r"[\w\u0600-\u06FF]+", lowered, flags=re.UNICODE)
    cleaned_tokens = [tok for tok in tokens if tok not in ar_stop and tok not in en_stop]
    return " ".join(cleaned_tokens)


def extract_chunk_id_from_metadata(controller, metadata: Optional[Any]) -> Optional[int]:
    metadata_dict = controller._coerce_metadata_dict(metadata)
    if not metadata_dict:
        return None
    chunk_id_value = metadata_dict.get("chunk_id")
    if chunk_id_value is None:
        return None
    try:
        return int(chunk_id_value)
    except (TypeError, ValueError):
        return None


def build_scored_doc_map(controller, documents: List[RetrievedDocument]):
    if not documents:
        return {}

    raw_scores = [float(getattr(doc, "score", 0.0) or 0.0) for doc in documents]
    score_min, score_max = min(raw_scores), max(raw_scores)
    denom = (score_max - score_min) or 1.0

    scored_map: Dict[str, Dict[str, Any]] = {}
    for idx, doc in enumerate(documents):
        norm = 1.0 if score_max == score_min else (
            (float(getattr(doc, "score", 0.0) or 0.0) - score_min) / denom
        )
        chunk_id = extract_chunk_id_from_metadata(controller, getattr(doc, "metadata", None))
        identifier = str(chunk_id) if chunk_id is not None else f"fallback_{idx}_{hash(doc.text)}"
        scored_map[identifier] = {"doc": doc, "score": norm}
    return scored_map


def fuse_dense_and_lexical_results(
    controller,
    dense_docs: Optional[List[RetrievedDocument]],
    lexical_docs: Optional[List[RetrievedDocument]],
    limit: int,
    dense_weight: float = 0.6,
) -> List[RetrievedDocument]:
    dense_docs = dense_docs or []
    lexical_docs = lexical_docs or []

    if not dense_docs and not lexical_docs:
        return []
    if not lexical_docs:
        return dense_docs[:limit]
    if not dense_docs:
        return lexical_docs[:limit]

    dense_map = build_scored_doc_map(controller, dense_docs)
    lexical_map = build_scored_doc_map(controller, lexical_docs)

    combined: Dict[str, Dict[str, Any]] = {}
    for key, payload in dense_map.items():
        combined[key] = {"doc": payload["doc"], "dense": payload["score"], "lex": 0.0}
    for key, payload in lexical_map.items():
        entry = combined.setdefault(key, {"doc": payload["doc"], "dense": 0.0, "lex": 0.0})
        entry["lex"] = max(entry["lex"], payload["score"])
        if entry["doc"] is None:
            entry["doc"] = payload["doc"]

    fused: List[RetrievedDocument] = []
    lexical_weight = max(0.0, min(1.0, 1.0 - dense_weight))
    for payload in combined.values():
        doc = payload["doc"]
        fused_score = dense_weight * payload["dense"] + lexical_weight * payload["lex"]
        doc.score = fused_score
        fused.append(doc)

    fused.sort(key=lambda d: getattr(d, "score", 0.0), reverse=True)
    return fused[:limit]


def clamp_unit(value: Optional[float], fallback: float) -> float:
    try:
        parsed = float(value if value is not None else fallback)
    except (TypeError, ValueError):
        parsed = fallback
    return max(0.0, min(1.0, parsed))


def compute_adaptive_history_weight(
    controller,
    configured_weight: Optional[float],
    followup_similarity: Optional[float],
    followup_threshold: Optional[float],
) -> float:
    base_weight = clamp_unit(
        configured_weight,
        getattr(controller.app_settings, "RAG_HISTORY_WEIGHT", 0.75),
    )
    threshold = clamp_unit(
        followup_threshold,
        getattr(controller.app_settings, "RAG_HISTORY_FOLLOWUP_SIM_THRESHOLD", 0.30),
    )
    conservative_weight = min(base_weight, 0.35)
    if followup_similarity is None:
        return conservative_weight
    try:
        similarity = float(followup_similarity)
    except (TypeError, ValueError):
        return conservative_weight
    if similarity >= threshold:
        return base_weight
    return conservative_weight


def fuse_query_and_history_results(
    controller,
    query_only_docs: Optional[List[RetrievedDocument]],
    history_aware_docs: Optional[List[RetrievedDocument]],
    limit: int,
    history_weight: float,
) -> List[RetrievedDocument]:
    query_only_docs = query_only_docs or []
    history_aware_docs = history_aware_docs or []
    if not query_only_docs and not history_aware_docs:
        return []
    if not history_aware_docs:
        return query_only_docs[:limit]
    if not query_only_docs:
        return history_aware_docs[:limit]

    query_map = build_scored_doc_map(controller, query_only_docs)
    history_map = build_scored_doc_map(controller, history_aware_docs)

    fused_weight = clamp_unit(history_weight, 0.75)
    query_weight = max(0.0, 1.0 - fused_weight)

    combined: Dict[str, Dict[str, Any]] = {}
    for key, payload in query_map.items():
        combined[key] = {
            "doc": payload["doc"],
            "query_score": payload["score"],
            "history_score": 0.0,
        }
    for key, payload in history_map.items():
        entry = combined.setdefault(
            key,
            {"doc": payload["doc"], "query_score": 0.0, "history_score": 0.0},
        )
        entry["history_score"] = max(entry["history_score"], payload["score"])
        if entry["doc"] is None:
            entry["doc"] = payload["doc"]

    fused: List[RetrievedDocument] = []
    for payload in combined.values():
        doc = payload["doc"]
        score = query_weight * payload["query_score"] + fused_weight * payload["history_score"]
        doc.score = score
        fused.append(doc)

    fused.sort(key=lambda item: getattr(item, "score", 0.0), reverse=True)
    return fused[:limit]


def build_conversation_context(
    controller,
    chat_messages: Optional[List[Dict[str, str]]],
    max_turns: Optional[int] = None,
) -> str:
    if not chat_messages:
        return ""

    turns = max_turns or getattr(controller.app_settings, "RAG_HISTORY_MAX_TURNS", 8)
    try:
        turns = int(turns)
    except (TypeError, ValueError):
        turns = 8
    turns = max(1, min(turns, 20))

    selected = chat_messages[-turns:]
    lines: List[str] = []
    for idx, message in enumerate(selected, 1):
        prompt = controller.generation_client.process_text((message.get("prompt") or "").strip())
        answer = controller.generation_client.process_text((message.get("answer") or "").strip())
        if prompt:
            lines.append(f"User[{idx}]: {prompt}")
        if answer:
            lines.append(f"Assistant[{idx}]: {answer}")
    return "\n".join(lines).strip()


async def search_vector_db_collection(
    controller,
    project,
    text: str,
    limit: int = 10,
    doc_types: Optional[List[str]] = None,
    asset_ids: Optional[List[int]] = None,
    keywords: Optional[List[str]] = None,
):
    collection_name = controller.create_collection_name(project_id=project.project_id)

    vectors = controller.embedding_client.embed_text(
        text=text,
        document_type=DocumentTypeEnum.QUERY.value,
    )
    if not vectors:
        return False

    query_vector = vectors[0] if isinstance(vectors, list) and vectors else None
    if not query_vector:
        return False

    results = await controller.vectordb_client.search_by_vector(
        collection_name=collection_name,
        vector=query_vector,
        limit=limit,
    )
    if not results:
        results = []

    lexical_results: List[RetrievedDocument] = []
    text_query = build_lexical_query(text or "")
    if text_query:
        if controller.search_client is not None:
            try:
                index_name = controller.search_client.get_index_name(project.project_id)
                filters: Dict[str, Any] = {"project_id": project.project_id}
                es_hits = await controller.search_client.search(
                    index_name=index_name,
                    query=text_query,
                    filters=filters,
                    size=limit,
                )
                for hit in es_hits:
                    text_value = hit.get("text") or ""
                    score_value = float(hit.get("_score") or 0.0)
                    meta: Dict[str, Any] = hit.get("metadata") or {}
                    for key in (
                        "asset_id",
                        "doc_type",
                        "document_type",
                        "chunk_id",
                        "page",
                        "page_number",
                        "original_filename",
                    ):
                        if key not in meta and key in hit:
                            meta[key] = hit.get(key)

                    lexical_results.append(
                        RetrievedDocument(text=text_value, score=score_value, metadata=meta)
                    )
            except Exception as exc:
                logger.error("Elasticsearch lexical search failed: %s", exc)
        else:
            lexical_results = await controller.vectordb_client.search_by_text(
                collection_name=collection_name,
                query=text_query,
                limit=limit,
            )

    dense_weight = getattr(controller.app_settings, "RETRIEVAL_DENSE_WEIGHT", 0.6)
    try:
        dense_weight = float(dense_weight)
    except (TypeError, ValueError):
        dense_weight = 0.6

    results = fuse_dense_and_lexical_results(
        controller,
        results,
        lexical_results,
        limit,
        dense_weight=dense_weight,
    )
    if not results:
        return []

    if doc_types:
        doc_types_normalized = {dt.lower() for dt in doc_types}
        filtered_results = []
        for result in results:
            metadata = getattr(result, "metadata", None)
            chunk_type = None
            if isinstance(metadata, dict):
                chunk_type = metadata.get("doc_type", metadata.get("document_type"))
            elif metadata is not None and hasattr(metadata, "get"):
                chunk_type = metadata.get("doc_type")

            if chunk_type and chunk_type.lower() in doc_types_normalized:
                filtered_results.append(result)
            elif chunk_type is None:
                filtered_results.append(result)

        if filtered_results:
            results = filtered_results
        else:
            return []

    if asset_ids:
        asset_id_set = {int(asset_id) for asset_id in asset_ids if asset_id is not None}
        filtered_results = []
        for result in results:
            metadata = getattr(result, "metadata", None)
            metadata_asset_id = None
            if isinstance(metadata, dict):
                metadata_asset_id = metadata.get("asset_id")
            elif metadata is not None and hasattr(metadata, "get"):
                metadata_asset_id = metadata.get("asset_id")

            if metadata_asset_id is not None:
                try:
                    if int(metadata_asset_id) in asset_id_set:
                        filtered_results.append(result)
                except (ValueError, TypeError):
                    continue

        if filtered_results:
            results = filtered_results
        else:
            return []

    if keywords:
        normalized_keywords = [kw.strip().lower() for kw in keywords if kw and kw.strip()]
        if normalized_keywords:
            filtered_results = []
            for result in results:
                text_value = getattr(result, "text", "") or ""
                t_lower = text_value.lower()
                if any(kw in t_lower for kw in normalized_keywords):
                    filtered_results.append(result)

            if filtered_results:
                results = filtered_results

    return results


async def rerank_documents(controller, query: str, documents: List[Any]) -> List[Any]:
    if (
        not query
        or not documents
        or not controller.reranker_client
        or controller.reranker_max_candidates <= 0
    ):
        return documents

    limit = min(controller.reranker_max_candidates, len(documents))
    candidate_texts = [(getattr(doc, "text", "") or "").strip() for doc in documents[:limit]]

    if not any(candidate_texts):
        return documents

    start_time = time.perf_counter()
    try:
        rerank_scores = await controller.reranker_client.rerank(
            query=query,
            documents=candidate_texts,
            top_n=limit,
        )
    except Exception as exc:
        logger.error("Reranker call failed: %s", exc)
        return documents

    duration_ms = int((time.perf_counter() - start_time) * 1000)
    logger.debug("Reranked %s candidates in %d ms", len(candidate_texts), duration_ms)

    if not rerank_scores:
        return documents

    score_lookup: Dict[int, float] = {}
    for entry in rerank_scores:
        idx = entry.get("index")
        if idx is None:
            continue
        try:
            idx_int = int(idx)
        except (TypeError, ValueError):
            continue
        if 0 <= idx_int < limit:
            score_lookup[idx_int] = float(entry.get("score") or 0.0)

    if not score_lookup:
        return documents

    ranked_slice = sorted(range(limit), key=lambda idx: score_lookup.get(idx, float("-inf")), reverse=True)
    reordered = [documents[idx] for idx in ranked_slice]
    if limit < len(documents):
        reordered.extend(documents[limit:])
    return reordered
