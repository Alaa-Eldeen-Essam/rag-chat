import json
import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional

from .BaseController import BaseController
from .nlp_analysis_orchestrator import (
    analyze_evidence_for_answer as orchestrate_analyze_evidence_for_answer,
    apply_ambiguity_gate as orchestrate_apply_ambiguity_gate,
    build_evidence_summary as orchestrate_build_evidence_summary,
    build_heuristic_analysis as orchestrate_build_heuristic_analysis,
    compact_clarification_option as orchestrate_compact_clarification_option,
    default_answer_metadata as orchestrate_default_answer_metadata,
    derive_clarification_option as orchestrate_derive_clarification_option,
    extract_conflict_signatures as orchestrate_extract_conflict_signatures,
    extract_json_object as orchestrate_extract_json_object,
    has_key_value_conflict as orchestrate_has_key_value_conflict,
    normalize_analysis_payload as orchestrate_normalize_analysis_payload,
)
from .nlp_direct_answer_orchestrator import (
    detect_question_type as orchestrate_detect_question_type,
    try_extract_direct_answer as orchestrate_try_extract_direct_answer,
)
from .nlp_generation_orchestrator import (
    generate_multihop_rag_answer as orchestrate_generate_multihop_rag_answer,
    generate_rag_answer_from_documents as orchestrate_generate_rag_answer_from_documents,
    generate_regular_chat_response as orchestrate_generate_regular_chat_response,
    summarize_chunks as orchestrate_summarize_chunks,
)
from .nlp_retrieval_orchestrator import (
    build_conversation_context as orchestrate_build_conversation_context,
    build_lexical_query as orchestrate_build_lexical_query,
    build_scored_doc_map as orchestrate_build_scored_doc_map,
    clamp_unit as orchestrate_clamp_unit,
    compute_adaptive_history_weight as orchestrate_compute_adaptive_history_weight,
    extract_chunk_id_from_metadata as orchestrate_extract_chunk_id_from_metadata,
    fuse_dense_and_lexical_results as orchestrate_fuse_dense_and_lexical_results,
    fuse_query_and_history_results as orchestrate_fuse_query_and_history_results,
    rerank_documents as orchestrate_rerank_documents,
    search_vector_db_collection as orchestrate_search_vector_db_collection,
)
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
        self._metrics_lock = threading.Lock()
        self._response_metrics: Dict[str, Dict[str, float]] = {
            "__global__": {"total": 0.0, "clarifications": 0.0, "parse_failures": 0.0}
        }

    def record_response_metrics(
        self,
        mode: str,
        needs_clarification: bool,
        parse_failed: bool,
    ) -> Dict[str, float]:
        normalized_mode = (mode or "unknown").strip().lower() or "unknown"
        with self._metrics_lock:
            global_bucket = self._response_metrics.setdefault(
                "__global__", {"total": 0.0, "clarifications": 0.0, "parse_failures": 0.0}
            )
            mode_bucket = self._response_metrics.setdefault(
                normalized_mode,
                {"total": 0.0, "clarifications": 0.0, "parse_failures": 0.0},
            )

            global_bucket["total"] += 1.0
            mode_bucket["total"] += 1.0
            if needs_clarification:
                global_bucket["clarifications"] += 1.0
                mode_bucket["clarifications"] += 1.0
            if parse_failed:
                global_bucket["parse_failures"] += 1.0
                mode_bucket["parse_failures"] += 1.0

            mode_total = max(1.0, mode_bucket["total"])
            global_total = max(1.0, global_bucket["total"])
            return {
                "mode_total": mode_bucket["total"],
                "mode_clarification_rate": mode_bucket["clarifications"] / mode_total,
                "mode_parse_failure_rate": mode_bucket["parse_failures"] / mode_total,
                "global_total": global_bucket["total"],
                "global_clarification_rate": global_bucket["clarifications"] / global_total,
                "global_parse_failure_rate": global_bucket["parse_failures"] / global_total,
            }

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
        return orchestrate_detect_question_type(query)

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
        return orchestrate_build_lexical_query(text)

    def _extract_chunk_id_from_metadata(self, metadata: Optional[Any]) -> Optional[int]:
        return orchestrate_extract_chunk_id_from_metadata(self, metadata)

    def _build_scored_doc_map(self, documents: List[RetrievedDocument]):
        return orchestrate_build_scored_doc_map(self, documents)

    def _fuse_dense_and_lexical_results(
        self,
        dense_docs: Optional[List[RetrievedDocument]],
        lexical_docs: Optional[List[RetrievedDocument]],
        limit: int,
        dense_weight: float = 0.6,
    ) -> List[RetrievedDocument]:
        return orchestrate_fuse_dense_and_lexical_results(
            self,
            dense_docs=dense_docs,
            lexical_docs=lexical_docs,
            limit=limit,
            dense_weight=dense_weight,
        )

    def _clamp_unit(self, value: Optional[float], fallback: float) -> float:
        return orchestrate_clamp_unit(value, fallback)

    def compute_adaptive_history_weight(
        self,
        configured_weight: Optional[float],
        followup_similarity: Optional[float],
        followup_threshold: Optional[float],
    ) -> float:
        return orchestrate_compute_adaptive_history_weight(
            self,
            configured_weight=configured_weight,
            followup_similarity=followup_similarity,
            followup_threshold=followup_threshold,
        )

    def fuse_query_and_history_results(
        self,
        query_only_docs: Optional[List[RetrievedDocument]],
        history_aware_docs: Optional[List[RetrievedDocument]],
        limit: int,
        history_weight: float,
    ) -> List[RetrievedDocument]:
        return orchestrate_fuse_query_and_history_results(
            self,
            query_only_docs=query_only_docs,
            history_aware_docs=history_aware_docs,
            limit=limit,
            history_weight=history_weight,
        )

    def build_conversation_context(
        self,
        chat_messages: Optional[List[Dict[str, str]]],
        max_turns: Optional[int] = None,
    ) -> str:
        return orchestrate_build_conversation_context(
            self,
            chat_messages=chat_messages,
            max_turns=max_turns,
        )

    def _default_answer_metadata(self) -> Dict[str, Any]:
        return orchestrate_default_answer_metadata(self)

    def _extract_json_object(self, text: Optional[str]) -> Optional[Dict[str, Any]]:
        return orchestrate_extract_json_object(self, text)

    def _normalize_analysis_payload(
        self,
        payload: Optional[Dict[str, Any]],
        query: str,
    ) -> Dict[str, Any]:
        return orchestrate_normalize_analysis_payload(self, payload, query)

    def _build_heuristic_analysis(
        self,
        query: str,
        documents: List[Any],
        asset_labels: Optional[Dict[int, str]] = None,
        asset_labels_by_name: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return orchestrate_build_heuristic_analysis(
            self,
            query=query,
            documents=documents,
            asset_labels=asset_labels,
            asset_labels_by_name=asset_labels_by_name,
        )

    def _build_evidence_summary(self, analysis: Dict[str, Any]) -> str:
        return orchestrate_build_evidence_summary(self, analysis)

    def _extract_conflict_signatures(self, text: str) -> List[tuple[str, str]]:
        return orchestrate_extract_conflict_signatures(self, text)

    def _has_key_value_conflict(
        self,
        analysis: Dict[str, Any],
        threshold: float,
        top_conf: float,
    ) -> bool:
        return orchestrate_has_key_value_conflict(
            self,
            analysis=analysis,
            threshold=threshold,
            top_conf=top_conf,
        )

    def _compact_clarification_option(self, text: str, max_len: int = 90) -> str:
        return orchestrate_compact_clarification_option(self, text, max_len=max_len)

    def _derive_clarification_option(self, answer_text: str) -> str:
        return orchestrate_derive_clarification_option(self, answer_text)

    def _apply_ambiguity_gate(
        self,
        analysis: Dict[str, Any],
        query: str,
        ambiguity_threshold: Optional[float],
        top_n: Optional[int],
    ) -> Dict[str, Any]:
        return orchestrate_apply_ambiguity_gate(
            self,
            analysis=analysis,
            query=query,
            ambiguity_threshold=ambiguity_threshold,
            top_n=top_n,
        )

    async def analyze_evidence_for_answer(
        self,
        query: str,
        retrieved_documents: List[Any],
        chat_messages: Optional[List[Dict[str, str]]] = None,
        conversation_context: Optional[str] = None,
        template_group: str = "rag",
        ambiguity_threshold: Optional[float] = None,
        asset_labels: Optional[Dict[int, str]] = None,
        asset_labels_by_name: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return await orchestrate_analyze_evidence_for_answer(
            self,
            query=query,
            retrieved_documents=retrieved_documents,
            chat_messages=chat_messages,
            conversation_context=conversation_context,
            template_group=template_group,
            ambiguity_threshold=ambiguity_threshold,
            asset_labels=asset_labels,
            asset_labels_by_name=asset_labels_by_name,
        )

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
        return await orchestrate_search_vector_db_collection(
            self,
            project=project,
            text=text,
            limit=limit,
            doc_types=doc_types,
            asset_ids=asset_ids,
            keywords=keywords,
        )

    async def rerank_documents(self, query: str, documents: List[Any]) -> List[Any]:
        return await orchestrate_rerank_documents(self, query=query, documents=documents)

    def _try_extract_direct_answer(self, query: str, documents: List[Any], question_type: str) -> Optional[str]:
        return orchestrate_try_extract_direct_answer(
            query=query,
            documents=documents,
            question_type=question_type,
        )

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
            metadata = self._default_answer_metadata()
            metadata["answer_confidence"] = 1.0
            return answer_text, None, None, metadata

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

    async def generate_multihop_rag_answer(
        self,
        project: Project,
        query: str,
        chat_messages: Optional[List[Dict[str, str]]] = None,
        stream: bool = False,
        collector: Optional[dict] = None,
        doc_types: Optional[List[str]] = None,
        asset_ids: Optional[List[int]] = None,
        max_hops: int = 2,
        per_hop_k: int = 6,
        per_hop_evidence: int = 3,
        generation_temperature: Optional[float] = None,
        answer_style: Optional[str] = None,
        conversation_context: Optional[str] = None,
        history_weight: Optional[float] = None,
        ambiguity_threshold: Optional[float] = None,
        force_clarification: Optional[bool] = None,
        project_asset_scope: Optional[Dict[int, List[int]]] = None,
    ):
        return await orchestrate_generate_multihop_rag_answer(
            self,
            project=project,
            query=query,
            chat_messages=chat_messages,
            stream=stream,
            collector=collector,
            doc_types=doc_types,
            asset_ids=asset_ids,
            max_hops=max_hops,
            per_hop_k=per_hop_k,
            per_hop_evidence=per_hop_evidence,
            generation_temperature=generation_temperature,
            answer_style=answer_style,
            conversation_context=conversation_context,
            history_weight=history_weight,
            ambiguity_threshold=ambiguity_threshold,
            force_clarification=force_clarification,
            project_asset_scope=project_asset_scope,
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
                            explain_retrieval: bool = False,
                            template_group: str = "rag",
                            conversation_context: Optional[str] = None,
                            ambiguity_threshold: Optional[float] = None,
                            force_clarification: Optional[bool] = None):
        return await orchestrate_generate_rag_answer_from_documents(
            self,
            retrieved_documents=retrieved_documents,
            query=query,
            chat_messages=chat_messages,
            stream=stream,
            collector=collector,
            asset_labels=asset_labels,
            asset_labels_by_name=asset_labels_by_name,
            direct_hint=direct_hint,
            answer_style=answer_style,
            explain_retrieval=explain_retrieval,
            template_group=template_group,
            conversation_context=conversation_context,
            ambiguity_threshold=ambiguity_threshold,
            force_clarification=force_clarification,
        )

    async def generate_regular_chat_response(
        self,
        query: str,
        chat_messages: Optional[List[Dict[str, str]]] = None,
        stream: bool = False,
        collector: Optional[dict] = None,
        answer_style: Optional[str] = None,
        explain_retrieval: bool = False,  # unused here but kept for API symmetry
    ):
        return await orchestrate_generate_regular_chat_response(
            self,
            query=query,
            chat_messages=chat_messages,
            stream=stream,
            collector=collector,
            answer_style=answer_style,
            explain_retrieval=explain_retrieval,
        )
    
    def summarize_chunks(self, chunks: List[DataChunk], focus: Optional[str] = None,
                         max_output_tokens: Optional[int] = None,
                         asset_labels: Optional[Dict[int, str]] = None,
                         asset_labels_by_name: Optional[Dict[str, str]] = None,
                         stream: bool = False,
                         collector: Optional[Dict[str, list]] = None):
        return orchestrate_summarize_chunks(
            self,
            chunks=chunks,
            focus=focus,
            max_output_tokens=max_output_tokens,
            asset_labels=asset_labels,
            asset_labels_by_name=asset_labels_by_name,
            stream=stream,
            collector=collector,
        )
