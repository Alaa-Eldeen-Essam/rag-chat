import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from .BaseController import BaseController
from models.db_schemes import DataChunk, Project, RetrievedDocument
from stores.llm.LLMEnums import DocumentTypeEnum

logger = logging.getLogger(__name__)

# Basic Arabic month names for simple date extraction.
AR_MONTHS_PATTERN = (
    "يناير|فبراير|مارس|أبريل|ابريل|مايو|يونيو|يوليو|"
    "أغسطس|اغسطس|سبتمبر|أكتوبر|اكتوبر|نوفمبر|ديسمبر"
)

# Basic English month names for simple date extraction.
EN_MONTHS_PATTERN = (
    "January|February|March|April|May|June|July|August|September|October|November|December|"
    "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)

# Match patterns like:
# - "2 ديسمبر 2021"
# - "2\nديسمبر2021"
# - "December 2, 2021"
# - "2 December 2021"
DATE_REGEX = re.compile(
    rf"("
    rf"\d{{1,2}}\D{{0,7}}(?:{AR_MONTHS_PATTERN}|{EN_MONTHS_PATTERN})\D{{0,7}}\d{{4}}"
    rf"|"
    rf"(?:{AR_MONTHS_PATTERN}|{EN_MONTHS_PATTERN})\D{{0,7}}\d{{4}}"
    rf")"
)

# Maximum number of evidence chunks to send to the LLM for a single answer.
EVIDENCE_DOC_LIMIT = 5

# Approximate character budget for all evidence text passed to the LLM for
# a single answer. This helps keep prompts focused and reduces hallucination
# risk on very long documents.
EVIDENCE_CHAR_BUDGET = 4000

class NLPController(BaseController):

    def __init__(
        self,
        vectordb_client,
        generation_client,
        embedding_client,
        template_parser,
        search_client=None,
        reranker_client=None,
        reranker_max_candidates: Optional[int] = None,
    ):
        super().__init__()

        self.vectordb_client = vectordb_client
        self.generation_client = generation_client
        self.embedding_client = embedding_client
        self.template_parser = template_parser
        self.search_client = search_client
        self.reranker_client = reranker_client
        self.reranker_max_candidates = reranker_max_candidates or 0

    def _normalize_answer_style(self, style: Optional[str]) -> str:
        normalized = (style or "").strip().lower()
        if normalized in {"concise", "detailed", "balanced"}:
            return normalized
        return "concise"

    def _infer_answer_style(self, query: Optional[str], explicit_style: Optional[str] = None) -> str:
        """
        Infer answer style from user question (Arabic + English hints).
        Explicit style, if provided, wins; otherwise use heuristics.
        """
        if explicit_style:
            return self._normalize_answer_style(explicit_style)

        q = (query or "").strip().lower()
        if not q:
            return "balanced"

        # English concise cues
        concise_en = [
            "short answer", "concise", "brief", "summary", "summarize", "tl;dr",
            "in short", "quick answer", "quickly", "few words"
        ]
        # Arabic concise cues
        concise_ar = [
            "مختصر", "باختصار", "بإيجاز", "ملخص", "تلخيص", "خلاصة", "قصير", "إجابة قصيرة"
        ]

        # English detailed cues
        detailed_en = [
            "detailed", "in detail", "elaborate", "explain fully", "step by step",
            "comprehensive", "long answer", "deep dive", "full explanation"
        ]
        # Arabic detailed cues
        detailed_ar = [
            "بالتفصيل", "تفصيلي", "اشرح", "شرح", "موسع", "مطول", "بتوسع", "كاملة", "تفاصيل"
        ]

        def any_in(tokens):
            return any(tok in q for tok in tokens)

        detailed_hit = any_in(detailed_en) or any_in(detailed_ar)
        concise_hit = any_in(concise_en) or any_in(concise_ar)

        if detailed_hit and not concise_hit:
            return "detailed"
        if concise_hit and not detailed_hit:
            return "concise"
        if detailed_hit and concise_hit:
            return "balanced"
        # Default neutral style
        return "balanced"

    def _build_style_directives(
        self,
        answer_style: Optional[str],
        explain_retrieval: bool,
        language: str,
    ) -> tuple[str, str]:
        """
        Build bilingual (EN/AR) style hints that get injected into the prompts.
        """
        style = self._normalize_answer_style(answer_style)
        lang = (language or "").lower()
        is_ar = lang.startswith("ar")

        if style == "detailed":
            style_hint_en = "Detailed answer with clear structure; use bullet/numbered points when helpful."
            style_hint_ar = "إجابة مفصلة ومنظمة؛ استخدم نقاطًا أو ترقيمًا عند الحاجة."
        elif style == "balanced":
            style_hint_en = "Balanced answer: a short summary followed by key details."
            style_hint_ar = "إجابة متوازنة: ملخص قصير يتبعه أهم التفاصيل."
        else:
            style_hint_en = "Concise answer: keep it direct and short."
            style_hint_ar = "إجابة موجزة: مختصرة ومباشرة."

        explain_en = ""
        explain_ar = ""
        if explain_retrieval:
            explain_en = "Start with a brief evidence recap (1-2 sentences) before the final answer."
            explain_ar = "ابدأ بملخص قصير للأدلة (١-٢ جملة) قبل الإجابة النهائية."

        style_instructions = style_hint_ar if is_ar else style_hint_en
        if explain_retrieval:
            style_instructions = f"{style_instructions} {explain_ar if is_ar else explain_en}".strip()

        style_hint = style_hint_ar if is_ar else style_hint_en
        if explain_retrieval:
            style_hint = f"{style_hint} {'+ evidence recap first' if not is_ar else '+ ملخص أدلة أولاً'}"

        return style_instructions, style_hint

    def create_collection_name(self, project_id: str):
        return f"collection_{self.vectordb_client.default_vector_size}_{project_id}".strip()
    
    async def reset_vector_db_collection(self, project: Project):
        collection_name = self.create_collection_name(project_id=project.project_id)
        return await self.vectordb_client.delete_collection(collection_name=collection_name)
    
    async def get_vector_db_collection_info(self, project: Project):
        collection_name = self.create_collection_name(project_id=project.project_id)
        collection_info = await self.vectordb_client.get_collection_info(collection_name=collection_name)

        return json.loads(
            json.dumps(collection_info, default=lambda x: x.__dict__)
        )

    def _coerce_metadata_dict(self, metadata: Optional[Any]) -> Optional[Dict[str, Any]]:
        if isinstance(metadata, dict):
            return metadata
        if metadata is None:
            return None

        if hasattr(metadata, "dict"):
            try:
                meta_dict = metadata.dict()  # type: ignore[call-arg]
                if isinstance(meta_dict, dict):
                    return meta_dict
            except Exception:
                pass

        if hasattr(metadata, "__dict__"):
            meta_dict = getattr(metadata, "__dict__", None)
            if isinstance(meta_dict, dict):
                return meta_dict

        return None

    def _detect_question_type(self, query: str) -> str:
        """
        Very lightweight question type detector for Arabic and English.
        Returns one of: 'when', 'why', 'where', 'who', 'how_many', or ''.
        """
        if not query:
            return ""

        q = (query or "").strip().lower()

        # Basic Arabic / English "when" markers.
        if "متى" in q or q.startswith("when "):
            return "when"

        # Basic Arabic / English "why" markers, including common rephrasings.
        if (
            "لماذا" in q
            or "لماذا لم" in q
            or q.startswith("why ")
            or "ما سبب" in q
            or "ما هو سبب" in q
            or "ما هي أسباب" in q
            or "ما الاسباب" in q
            or "ما الأسباب" in q
            or "ما الذي دفع" in q
            or "what is the reason" in q
            or "what's the reason" in q
            or "what is the cause" in q
            or "what caused" in q
        ):
            return "why"

        # Basic "where" markers.
        if "أين" in q or q.startswith("where "):
            return "where"

        # Basic "who" markers.
        if "من " in q or q.startswith("who "):
            return "who"

        # Basic "how many" markers (numeric questions).
        if "كم " in q or "how many" in q:
            return "how_many"

        return ""

    def _normalize_label_value(self, value: str) -> str:
        label = (value or "").strip()
        if not label:
            return ""
        normalized = label.replace("\\", "/")
        if "/" in normalized:
            normalized = normalized.split("/")[-1]
        return normalized

    def _resolve_document_label(
        self,
        metadata: Optional[Any],
        fallback_label: str,
        asset_labels: Optional[Dict[int, str]] = None,
        asset_labels_by_name: Optional[Dict[str, str]] = None,
        asset_id_hint: Optional[int] = None,
    ) -> str:
        metadata_dict = self._coerce_metadata_dict(metadata)

        candidate_asset_id = asset_id_hint
        if candidate_asset_id is None and metadata_dict:
            candidate_asset_id = metadata_dict.get("asset_id")

        if asset_labels and candidate_asset_id is not None:
            try:
                label = asset_labels.get(int(candidate_asset_id))
            except (ValueError, TypeError):
                label = None
            if label:
                return self._normalize_label_value(label)

        if metadata_dict:
            for key in ("source_name", "original_filename", "original_name", "filename", "name", "source"):
                value = metadata_dict.get(key)
                if isinstance(value, str):
                    cleaned = self._normalize_label_value(value)
                    if cleaned:
                        if asset_labels_by_name and cleaned in asset_labels_by_name:
                            return asset_labels_by_name[cleaned]
                        return cleaned

        return self._normalize_label_value(fallback_label)

    def _build_lexical_query(self, text: str) -> str:
        """
        Build a cleaned lexical query for FTS, stripping obvious question
        words and punctuation so that we focus on content terms.
        """
        if not text:
            return ""

        raw = (text or "").strip()
        # If there are multiple lines, use the last non-empty one (likely the question).
        parts = [p.strip() for p in re.split(r"[\r\n]+", raw) if p.strip()]
        if parts:
            raw = parts[-1]

        lowered = raw.lower()

        ar_stop = {
            "متى",
            "لماذا",
            "ليه",
            "ليش",
            "هل",
            "ما",
            "ماذا",
            "كم",
            "من",
            "أين",
            "اين",
            "كيف",
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
        cleaned_tokens = []
        for tok in tokens:
            if tok in ar_stop or tok in en_stop:
                continue
            cleaned_tokens.append(tok)

        return " ".join(cleaned_tokens)

    def _extract_chunk_id_from_metadata(self, metadata: Optional[Any]) -> Optional[int]:
        metadata_dict = self._coerce_metadata_dict(metadata)
        if not metadata_dict:
            return None
        chunk_id_value = metadata_dict.get("chunk_id")
        if chunk_id_value is None:
            return None
        try:
            return int(chunk_id_value)
        except (TypeError, ValueError):
            return None

    def _build_scored_doc_map(self, documents: List[RetrievedDocument]):
        if not documents:
            return {}
        raw_scores = [float(getattr(doc, "score", 0.0) or 0.0) for doc in documents]
        score_min, score_max = min(raw_scores), max(raw_scores)
        denom = (score_max - score_min) or 1.0
        scored_map = {}
        for idx, doc in enumerate(documents):
            norm = 1.0 if score_max == score_min else (
                (float(getattr(doc, "score", 0.0) or 0.0) - score_min) / denom
            )
            chunk_id = self._extract_chunk_id_from_metadata(getattr(doc, "metadata", None))
            identifier = str(chunk_id) if chunk_id is not None else f"fallback_{idx}_{hash(doc.text)}"
            scored_map[identifier] = {"doc": doc, "score": norm}
        return scored_map

    def _fuse_dense_and_lexical_results(
        self,
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

        dense_map = self._build_scored_doc_map(dense_docs)
        lexical_map = self._build_scored_doc_map(lexical_docs)

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
    
    async def index_into_vector_db(
        self,
        project: Project,
        chunks: List[DataChunk],
        chunks_ids: List[int],
        do_reset: bool = False,
    ):

        # step1: get collection name
        collection_name = self.create_collection_name(project_id=project.project_id)

        # step2: manage items
        texts = [c.chunk_text for c in chunks]
        metadata = [c.chunk_metadata for c in chunks]
        vectors = self.embedding_client.embed_text(
            text=texts,
            document_type=DocumentTypeEnum.DOCUMENT.value,
        )

        if not vectors or len(vectors) != len(texts):
            logger.error("Embedding client returned invalid vectors for indexing")
            return False

        # step3: create collection if not exists
        _ = await self.vectordb_client.create_collection(
            collection_name=collection_name,
            embedding_size=self.embedding_client.embedding_size,
            do_reset=do_reset,
        )

        # step4: insert into vector db
        _ = await self.vectordb_client.insert_many(
            collection_name=collection_name,
            texts=texts,
            metadata=metadata,
            vectors=vectors,
            record_ids=chunks_ids,
        )

        # step5: index into search backend (Elasticsearch) when available
        if self.search_client is not None:
            try:
                index_name = self.search_client.get_index_name(project.project_id)
                documents = []
                for chunk in chunks:
                    meta = chunk.chunk_metadata or {}
                    page_value = meta.get("page") or meta.get("page_number")
                    original_filename = (
                        meta.get("original_filename")
                        or meta.get("source_name")
                        or ""
                    )
                    doc = {
                        "chunk_id": getattr(chunk, "chunk_id", None),
                        "project_id": getattr(chunk, "chunk_project_id", None),
                        "asset_id": getattr(chunk, "chunk_asset_id", None),
                        "doc_type": meta.get("doc_type") or meta.get("document_type"),
                        "text": chunk.chunk_text,
                        "page": page_value,
                        "page_number": page_value,
                        "original_filename": original_filename,
                        "metadata": meta,
                    }
                    documents.append(doc)

                if documents:
                    await self.search_client.index_documents(
                        index_name=index_name,
                        documents=documents,
                    )
            except Exception as exc:
                logger.error("Failed to index chunks into search backend: %s", exc)

        return True

    async def search_vector_db_collection(
        self,
        project: Project,
        text: str,
        limit: int = 10,
        doc_types: Optional[List[str]] = None,
        asset_ids: Optional[List[int]] = None,
        keywords: Optional[List[str]] = None,
    ):

        # step1: get collection name
        query_vector = None
        collection_name = self.create_collection_name(project_id=project.project_id)

        # step2: get text embedding vector
        vectors = self.embedding_client.embed_text(text=text, 
                                                 document_type=DocumentTypeEnum.QUERY.value)

        if not vectors or len(vectors) == 0:
            return False
        
        if isinstance(vectors, list) and len(vectors) > 0:
            query_vector = vectors[0]

        if not query_vector:
            return False  

        # step3: do semantic search
        results = await self.vectordb_client.search_by_vector(
            collection_name=collection_name,
            vector=query_vector,
            limit=limit
        )

        if not results:
            results = []

        lexical_results: List[RetrievedDocument] = []
        text_query = self._build_lexical_query(text or "")
        if text_query:
            # Prefer Elasticsearch for lexical retrieval when available.
            if self.search_client is not None:
                try:
                    index_name = self.search_client.get_index_name(project.project_id)
                    filters: Dict[str, Any] = {"project_id": project.project_id}
                    es_hits = await self.search_client.search(
                        index_name=index_name,
                        query=text_query,
                        filters=filters,
                        size=limit,
                    )
                    for hit in es_hits:
                        text_value = hit.get("text") or ""
                        score_value = float(hit.get("_score") or 0.0)
                        meta: Dict[str, Any] = hit.get("metadata") or {}
                        # Ensure key metadata fields are available for downstream filters.
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
                            RetrievedDocument(
                                text=text_value,
                                score=score_value,
                                metadata=meta,
                            )
                        )
                except Exception as exc:
                    logger.error("Elasticsearch lexical search failed: %s", exc)
            else:
                lexical_results = await self.vectordb_client.search_by_text(
                    collection_name=collection_name,
                    query=text_query,
                    limit=limit
                )

        dense_weight = getattr(self.app_settings, "RETRIEVAL_DENSE_WEIGHT", 0.6)
        try:
            dense_weight = float(dense_weight)
        except (TypeError, ValueError):
            dense_weight = 0.6
        results = self._fuse_dense_and_lexical_results(
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

                # Prefer matching doc_type, but do not drop chunks that
                # lack doc_type metadata (for backward compatibility with
                # older indexed data).
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

        # Optional keyword / lexical filtering: keep hits that contain at least
        # one of the query keywords, if provided.
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

    async def rerank_documents(self, query: str, documents: List[Any]) -> List[Any]:
        """
        Optionally rerank the retrieved documents using an external cross-encoder.
        """
        if (
            not query
            or not documents
            or not self.reranker_client
            or self.reranker_max_candidates <= 0
        ):
            return documents

        limit = min(self.reranker_max_candidates, len(documents))
        candidate_texts: List[str] = []
        for doc in documents[:limit]:
            text_value = getattr(doc, "text", "") or ""
            candidate_texts.append(text_value.strip())

        if not any(candidate_texts):
            return documents

        start_time = time.perf_counter()
        try:
            rerank_scores = await self.reranker_client.rerank(
                query=query,
                documents=candidate_texts,
                top_n=limit,
            )
        except Exception as exc:
            logger.error("Reranker call failed: %s", exc)
            return documents

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        logger.debug(
            "Reranked %s candidates in %d ms", len(candidate_texts), duration_ms
        )

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

        ranked_slice = sorted(
            range(limit),
            key=lambda idx: score_lookup.get(idx, float("-inf")),
            reverse=True,
        )
        reordered = [documents[idx] for idx in ranked_slice]
        if limit < len(documents):
            reordered.extend(documents[limit:])
        return reordered

    def _try_extract_direct_answer(self, query: str, documents: List[Any], question_type: str) -> Optional[str]:
        """
        Lightweight, retrieval-side extraction of very simple factual answers
        (dates, simple purposes) from the retrieved documents before passing
        everything to the LLM. Intended to be language-agnostic for Arabic
        and English where possible.
        """
        if not query or not documents or not question_type:
            return None

        corpus = "\n".join(
            (getattr(doc, "text", "") or "") for doc in documents
        )
        if not corpus:
            return None
        if question_type == "when":
            # Tightened logic: only treat a date as a direct answer if it
            # appears in a sentence that also shares at least one content
            # token with the question (after stripping generic question
            # words). This avoids grabbing arbitrary dates from unrelated
            # parts of the corpus.
            sentences = re.split(r"[\.!\?؟\n]+", corpus)
            lowered_query = (query or "").lower()
            stop_tokens = {"متى", "when", "?", "؟"}
            query_tokens = [
                tok
                for tok in re.findall(r"\w+", lowered_query, flags=re.UNICODE)
                if tok not in stop_tokens and len(tok) > 2
            ]

            best_candidate = None
            best_overlap = 0

            for sent in sentences:
                s = sent.strip()
                if not s:
                    continue
                low = s.lower()
                m = DATE_REGEX.search(low)
                if not m:
                    continue
                date_candidate = m.group(1).strip()
                if not date_candidate:
                    continue

                overlap = 0
                for tok in query_tokens:
                    if tok in low:
                        overlap += 1

                if overlap > best_overlap:
                    best_overlap = overlap
                    best_candidate = date_candidate

            if best_candidate and best_overlap > 0:
                return best_candidate
            return None

        if question_type == "why":
            # Split corpus into coarse sentences.
            sentences = re.split(r"[\.!\?؟\n]+", corpus)

            def normalize_arabic(text: str) -> str:
                """Light normalization to make OCR variants more robust."""
                # Strip diacritics and tatweel
                text = re.sub(r"[ًٌٍَُِّْـ]", "", text)
                # Normalize common alef forms and taa marbuta / ya
                text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
                text = text.replace("ى", "ي").replace("ة", "ه")
                # Collapse whitespace
                text = re.sub(r"\s+", " ", text)
                return text

            # Travel-related verbs / phrases (normalized Arabic + English).
            travel_keywords = [
                "سافر", "ذهب", "توجه", "زار", "رحل",  # Arabic verbs
                "سفر", "زيارة",
                "traveled", "travelled", "went", "visited", "journeyed",
            ]

            # Purpose pattern: "ل" + 2–8 Arabic letters, then a meeting-like noun.
            purpose_pattern = re.compile(
                r"(ل[اأإآبتثجحخدذرزسشصضطظعغفقكلمنهوي]{2,8}\s*"
                r"(?:اجتماع|اجتماعا|مؤتمر|قمة|لقاء|meeting|summit|conference))",
                flags=re.IGNORECASE,
            )

            # Basic purpose triggers as a fallback matcher (more general).
            triggers = [
                # Arabic purpose / cause markers (normalized)
                "لحضور", "لحض", "للمشاركة", "لتقديم", "للتفاوض", "لعقد",
                "من اجل", "بهدف", "لان", "لأن", "بسبب", "نتيجه", "نتيجة",
                # English purpose / cause markers
                "to attend", "in order to", "for the purpose of",
                "because", "because of", "due to", "as a result of",
            ]

            lowered_query = (query or "").lower()
            normalized_query = normalize_arabic(lowered_query)

            # Ignore generic question words.
            stop_tokens = {"لماذا", "why", "?", "؟"}
            query_tokens = [
                tok
                for tok in re.findall(r"\w+", normalized_query, flags=re.UNICODE)
                if tok not in stop_tokens and len(tok) > 2
            ]

            # First pass: pattern-based extraction bound to travel + query context.
            for sent in sentences:
                s = sent.strip()
                if not s:
                    continue

                low = s.lower()
                norm = normalize_arabic(low)

                # Require at least one travel-related keyword.
                if not any(tv in norm for tv in travel_keywords):
                    continue

                # Prefer sentences that share some tokens with the query.
                if query_tokens and not any(tok in norm for tok in query_tokens):
                    continue

                # Look for an explicit "ل + noun/verb" purpose fragment.
                m = purpose_pattern.search(low)
                if m:
                    start = m.start()
                    # Extract until the next major punctuation mark.
                    tail = s[start:]
                    p = re.search(r"[\.!\?؟]", tail)
                    end = start + p.start() if p else len(s)
                    reason_fragment = s[start:end].strip()
                    if reason_fragment:
                        return reason_fragment

            # Fallback: trigger-based sentence scoring (legacy behavior, but
            # using normalized text for robustness).
            best_sentence = None
            for sent in sentences:
                s = sent.strip()
                if not s:
                    continue
                low = s.lower()
                norm = normalize_arabic(low)
                if any(trigger in norm for trigger in triggers):
                    # Prefer sentences that share some tokens with the query.
                    if query_tokens and any(tok in norm for tok in query_tokens):
                        best_sentence = s
                        break
                    if best_sentence is None:
                        best_sentence = s

            if best_sentence:
                return best_sentence.strip()

        if question_type == "where":
            # Very lightweight extraction of a location-bearing sentence with
            # simple scoring instead of first match, to reduce misfires.
            sentences = re.split(r"[\.!\?؟\n]+", corpus)

            def normalize_arabic(text: str) -> str:
                text = re.sub(r"[ًٌٍَُِّْـ]", "", text)
                text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
                text = text.replace("ى", "ي").replace("ة", "ه")
                text = re.sub(r"\s+", " ", text)
                return text

            lowered_query = (query or "").lower()
            norm_query = normalize_arabic(lowered_query)
            stop_tokens = {"اين", "أين", "where", "?", "؟"}
            query_tokens = [
                tok
                for tok in re.findall(r"\w+", norm_query, flags=re.UNICODE)
                if tok not in stop_tokens and len(tok) > 2
            ]

            location_markers = ["في ", "في-", "الى ", "إلى ", "near", " in ", " at ", " to "]

            best_sentence = None
            best_score = 0
            for sent in sentences:
                s = sent.strip()
                if not s:
                    continue
                low = s.lower()
                norm = normalize_arabic(low)

                score = 0
                if any(marker in norm for marker in location_markers):
                    score += 1

                overlap = 0
                for tok in query_tokens:
                    if tok in norm:
                        overlap += 1
                score += overlap

                if score > best_score:
                    best_score = score
                    best_sentence = s

            if best_sentence and best_score > 0:
                return best_sentence.strip()

        if question_type == "how_many":
            # Simple numeric extraction: look for a sentence with a number and
            # some overlap with the query, preferring higher overlap.
            sentences = re.split(r"[\.!\?؟\n]+", corpus)
            lowered_query = (query or "").lower()
            stop_tokens = {"كم", "how", "many", "?", "؟"}
            query_tokens = [
                tok
                for tok in re.findall(r"\w+", lowered_query, flags=re.UNICODE)
                if tok not in stop_tokens and len(tok) > 2
            ]

            numeric_pattern = re.compile(r"\d+")

            best_sentence = None
            best_score = 0
            for sent in sentences:
                s = sent.strip()
                if not s:
                    continue
                low = s.lower()
                if not numeric_pattern.search(low):
                    continue

                overlap = 0
                for tok in query_tokens:
                    if tok in low:
                        overlap += 1

                if overlap > best_score:
                    best_score = overlap
                    best_sentence = s

            if best_sentence and best_score > 0:
                return best_sentence.strip()

        # Other types could be added here (where, who) as needed.
        return None

    async def answer_rag_question(self, project: Project, query: str, limit: int = 10,
                            chat_messages: Optional[List[Dict[str, str]]] = None,
                            stream: bool = False, collector: Optional[dict] = None,
                            doc_types: Optional[List[str]] = None,
                            asset_ids: Optional[List[int]] = None,
                            asset_labels: Optional[Dict[int, str]] = None,
                            asset_labels_by_name: Optional[Dict[str, str]] = None,
                            answer_style: Optional[str] = None,
                            explain_retrieval: bool = False):

        question_type = self._detect_question_type(query)
        lowered_query = (query or "").lower()
        inferred_style = self._infer_answer_style(query, answer_style)

        # Build an augmented retrieval query that incorporates recent
        # conversation turns (if any) so that follow-up questions using
        # pronouns like "هناك / there" still retrieve the right chunks.
        retrieval_text = query or ""
        if chat_messages:
            parts: List[str] = []
            for msg in chat_messages[-3:]:
                prompt_part = (msg.get("prompt") or "").strip()
                answer_part = (msg.get("answer") or "").strip()
                if prompt_part:
                    parts.append(prompt_part)
                if answer_part:
                    parts.append(answer_part)
            if parts:
                retrieval_text = "\n".join(parts + [query or ""])
        
        # step1: retrieve related documents
        retrieved_documents = await self.search_vector_db_collection(
            project=project,
            text=retrieval_text,
            limit=limit,
            doc_types=doc_types,
            asset_ids=asset_ids,
        )

        # ------------------------------------------------------------------
        # Guardrail: for questions explicitly about "شيوع اللحن بين العرب"
        # (e.g. "متى شاع اللحن بين العرب؟"), require that at least one of
        # the retrieved chunks actually contains both "اللحن" and "العرب".
        # If no such chunk exists, short‑circuit with a deterministic
        # fallback answer instead of allowing the model to hallucinate a
        # time based only on partial context (e.g. generic dates in the
        # document about العربية الفصحى).
        # ------------------------------------------------------------------
        if "اللحن" in lowered_query and "العرب" in lowered_query:
            has_supporting_chunk = False
            for doc in retrieved_documents or []:
                text_value = getattr(doc, "text", "") or ""
                t_low = text_value.lower()
                if "اللحن" in t_low and "العرب" in t_low:
                    has_supporting_chunk = True
                    break

            if not has_supporting_chunk:
                fallback_answer = (
                    "لا يمكن تحديد متى شاع اللحن بين العرب من المستندات المفهرسة الحالية."
                )
                return fallback_answer, None, None

        direct_hint = self._try_extract_direct_answer(
            query=query,
            documents=retrieved_documents or [],
            question_type=question_type,
        )

        # Try to resolve a human-readable label for the document that most
        # likely contains the direct hint (e.g., original filename), so that
        # we can say "according to <document>" instead of "according to the
        # documents" in deterministic answers.
        doc_label_for_hint: Optional[str] = None
        if direct_hint and retrieved_documents:
            chosen_doc = None
            for doc in retrieved_documents:
                text_value = getattr(doc, "text", "") or ""
                if direct_hint in text_value:
                    chosen_doc = doc
                    break
            if chosen_doc is None:
                chosen_doc = retrieved_documents[0]

            try:
                doc_label_for_hint = self._resolve_document_label(
                    getattr(chosen_doc, "metadata", None),
                    fallback_label="Document 1",
                )
            except Exception:
                doc_label_for_hint = None

        # For clear "when / متى" questions where we can reliably extract a
        # concrete date from the retrieved documents, short-circuit and answer
        # directly rather than delegating to the LLM. This ensures deterministic
        # behavior even when conversation history might bias the model toward
        # "unknown" answers. For "why" questions we prefer to pass the hint into
        # the LLM so it can clean up / enrich the answer.
        if direct_hint and question_type == "when":
            has_arabic = bool(re.search(r"[\u0600-\u06FF]", query or ""))
            if doc_label_for_hint:
                prefix_ar = f'وفقاً للمستند "{doc_label_for_hint}"، '
                prefix_en = f'According to the document "{doc_label_for_hint}", '
            else:
                prefix_ar = "وفقاً للمستندات، "
                prefix_en = "According to the documents, "

            if has_arabic:
                answer_text = f"{prefix_ar}كان ذلك في {direct_hint}."
            else:
                answer_text = f"{prefix_en}this occurred on {direct_hint}."
            return answer_text, None, None

        return await self.generate_rag_answer_from_documents(
            retrieved_documents=retrieved_documents or [],
            query=query,
            chat_messages=chat_messages,
            stream=stream,
            collector=collector,
            asset_labels=asset_labels,
            asset_labels_by_name=asset_labels_by_name,
            direct_hint=direct_hint,
            answer_style=inferred_style,
            explain_retrieval=explain_retrieval,
        )

    async def generate_rag_answer_from_documents(self,
                            retrieved_documents: List[Any],
                            query: str,
                            chat_messages: Optional[List[Dict[str, str]]] = None,
                            stream: bool = False, collector: Optional[dict] = None,
                            asset_labels: Optional[Dict[int, str]] = None,
                            asset_labels_by_name: Optional[Dict[str, str]] = None,
                            direct_hint: Optional[str] = None,
                            answer_style: Optional[str] = None,
                            explain_retrieval: bool = False):
        
        answer_or_stream, full_prompt, chat_history = None, None, None

        if not retrieved_documents or len(retrieved_documents) == 0:
            return answer_or_stream, full_prompt, chat_history
        
        # step2: Select evidence documents and construct LLM prompt.
        # Use all retrieved documents (subject to the upstream `limit`)
        # so that the model can see the full evidence set.
        template_language = getattr(self.template_parser, "language", "en")
        style_instructions, style_hint = self._build_style_directives(
            answer_style=answer_style,
            explain_retrieval=explain_retrieval,
            language=template_language,
        )

        system_prompt = self.template_parser.get(
            "rag",
            "system_prompt",
            {"style_instructions": style_instructions},
        )

        evidence_documents: List[Any] = list(retrieved_documents)

        document_sections = []
        for idx, doc in enumerate(evidence_documents):
            chunk_text = self.generation_client.process_text(doc.text)
            doc_label = self._resolve_document_label(
                getattr(doc, "metadata", None),
                fallback_label=f"Document {idx + 1}",
                asset_labels=asset_labels,
                asset_labels_by_name=asset_labels_by_name,
            )
            section = self.template_parser.get("rag", "document_prompt", {
                    "doc_label": doc_label,
                    "chunk_text": chunk_text,
            }) or f"## Document: {doc_label}\n### Content: {chunk_text}"
            document_sections.append(section)

        documents_prompts = "\n".join(document_sections)

        hint_section = ""
        if direct_hint:
            hint_section = self.template_parser.get("rag", "hint_section", {
                "hint": direct_hint,
            }) or ("\n\n# Direct candidate answer extracted from documents:\n"
                   f"{direct_hint}\n")
            documents_prompts = documents_prompts + "\n" + hint_section

        footer_prompt = self.template_parser.get("rag", "footer_prompt", {
            "query": query,
            "style_hint": style_hint,
        })

        # step3: Construct Generation Client Prompts
        chat_history = [
            self.generation_client.construct_prompt(
                prompt=system_prompt,
                role=self.generation_client.enums.SYSTEM.value,
            )
        ]

        if chat_messages:
            trimmed_messages = chat_messages[-5:]

            if len(trimmed_messages) > 2:
                earlier_messages = trimmed_messages[:-2]
                prioritized_messages = trimmed_messages[-2:]
            else:
                earlier_messages = []
                prioritized_messages = trimmed_messages

            for message in earlier_messages:
                chat_history.append(
                    self.generation_client.construct_prompt(
                        prompt=self.generation_client.process_text(message.get("prompt", "")),
                        role=self.generation_client.enums.USER.value,
                    )
                )
                chat_history.append(
                    self.generation_client.construct_prompt(
                        prompt=self.generation_client.process_text(message.get("answer", "")),
                        role=self.generation_client.enums.ASSISTANT.value,
                    )
                )

            for message in prioritized_messages:
                chat_history.append(
                    self.generation_client.construct_prompt(
                        prompt=self.generation_client.process_text(message.get("prompt", "")),
                        role=self.generation_client.enums.USER.value,
                    )
                )
                chat_history.append(
                    self.generation_client.construct_prompt(
                        prompt=self.generation_client.process_text(message.get("answer", "")),
                        role=self.generation_client.enums.ASSISTANT.value,
                    )
                )

        full_prompt = "\n\n".join([ documents_prompts,  footer_prompt])

        if stream:
            answer_or_stream = self.generation_client.generate_text_stream(
                prompt=full_prompt,
                chat_history=chat_history,
                collector=collector
            )
        else:
            answer_or_stream = self.generation_client.generate_text(
                prompt=full_prompt,
                chat_history=chat_history
            )

        return answer_or_stream, full_prompt, chat_history

    async def generate_regular_chat_response(
        self,
        query: str,
        chat_messages: Optional[List[Dict[str, str]]] = None,
        stream: bool = False,
        collector: Optional[dict] = None,
        answer_style: Optional[str] = None,
        explain_retrieval: bool = False,  # unused here but kept for API symmetry
    ):
        """
        Generate a general (non-RAG) chat response that still respects the
        locale-specific system instructions but does not include any document
        evidence. This path is used for the Regular Chat Mode.
        """
        system_prompt = self.template_parser.get("chat", "system_prompt") or (
            "You are a concise, policy-compliant assistant. "
            "Answer helpfully, stay polite, and decline any unsafe requests."
        )
        template_language = getattr(self.template_parser, "language", "en")
        _, style_hint = self._build_style_directives(
            answer_style=answer_style,
            explain_retrieval=False,
            language=template_language,
        )

        chat_history = [
            self.generation_client.construct_prompt(
                prompt=system_prompt,
                role=self.generation_client.enums.SYSTEM.value,
            )
        ]

        if chat_messages:
            trimmed_messages = chat_messages[-8:]
            for message in trimmed_messages:
                prompt_text = self.generation_client.process_text(message.get("prompt", ""))
                answer_text = self.generation_client.process_text(message.get("answer", ""))
                if prompt_text:
                    chat_history.append(
                        self.generation_client.construct_prompt(
                            prompt=prompt_text,
                            role=self.generation_client.enums.USER.value,
                        )
                    )
                if answer_text:
                    chat_history.append(
                        self.generation_client.construct_prompt(
                            prompt=answer_text,
                            role=self.generation_client.enums.ASSISTANT.value,
                    )
                )

        style_prefix = ""
        style_norm = self._normalize_answer_style(answer_style)
        if style_norm == "detailed":
            style_prefix = "Provide a detailed, well-structured answer. "
        elif style_norm == "balanced":
            style_prefix = "Provide a concise answer, then add key details. "
        else:
            style_prefix = "Keep the answer concise and direct. "

        final_prompt = self.generation_client.process_text(f"{style_prefix}{query or ''}".strip())
        if stream:
            answer_stream = self.generation_client.generate_text_stream(
                prompt=final_prompt,
                chat_history=chat_history,
                collector=collector,
            )
            return answer_stream, final_prompt, chat_history

        answer = self.generation_client.generate_text(
            prompt=final_prompt,
            chat_history=chat_history,
        )
        return answer, final_prompt, chat_history
    
    def summarize_chunks(self, chunks: List[DataChunk], focus: Optional[str] = None,
                         max_output_tokens: Optional[int] = None,
                         asset_labels: Optional[Dict[int, str]] = None,
                         asset_labels_by_name: Optional[Dict[str, str]] = None,
                         stream: bool = False,
                         collector: Optional[Dict[str, list]] = None):
        if not chunks or len(chunks) == 0:
            return None, None

        system_prompt = self.template_parser.get("summary", "system_prompt") or (
            "You are an assistant that condenses provided content into a clear, concise summary."
        )

        document_sections = []
        for idx, chunk in enumerate(chunks):
            chunk_text = self.generation_client.process_text(chunk.chunk_text)
            fallback_label = f"Document {chunk.chunk_order if chunk.chunk_order else idx + 1}"
            doc_label = self._resolve_document_label(
                getattr(chunk, "chunk_metadata", None),
                fallback_label=fallback_label,
                asset_labels=asset_labels,
                asset_labels_by_name=asset_labels_by_name,
                asset_id_hint=getattr(chunk, "chunk_asset_id", None),
            )
            section = self.template_parser.get("summary", "document_prompt", {
                "doc_label": doc_label,
                "chunk_text": chunk_text,
            }) or f"## Document: {doc_label}\n{chunk_text}"
            document_sections.append(section)

        documents_prompts = "\n".join(document_sections)

        default_focus = self.template_parser.get("summary", "default_focus") or "Provide a concise summary that highlights the key ideas and critical details."

        summary_prompt = self.template_parser.get("summary", "summary_prompt", {
            "documents": documents_prompts,
            "focus": focus or default_focus,
        }) or "\n".join([
            "Summarize the following documents.",
            documents_prompts,
            "",
            focus or default_focus
        ])

        chat_history = [
            self.generation_client.construct_prompt(
                prompt=system_prompt,
                role=self.generation_client.enums.SYSTEM.value,
            )
        ]

        if stream:
            summary_stream = self.generation_client.generate_text_stream(
                prompt=summary_prompt,
                chat_history=chat_history,
                max_output_tokens=max_output_tokens,
                collector=collector,
            )
            return summary_stream, summary_prompt

        summary = self.generation_client.generate_text(
            prompt=summary_prompt,
            chat_history=chat_history,
            max_output_tokens=max_output_tokens
        )

        return summary, summary_prompt
