import threading
from typing import Any, Dict, List, Optional

from .BaseController import BaseController
from .nlp_analysis_orchestrator import (
    analyze_evidence_for_answer as orchestrate_analyze_evidence_for_answer,
    apply_ambiguity_gate as orchestrate_apply_ambiguity_gate,
    build_evidence_summary as orchestrate_build_evidence_summary,
    build_heuristic_analysis as orchestrate_build_heuristic_analysis,
    coerce_metadata_dict as orchestrate_coerce_metadata_dict,
    compact_clarification_option as orchestrate_compact_clarification_option,
    default_answer_metadata as orchestrate_default_answer_metadata,
    derive_clarification_option as orchestrate_derive_clarification_option,
    extract_conflict_signatures as orchestrate_extract_conflict_signatures,
    extract_json_object as orchestrate_extract_json_object,
    has_key_value_conflict as orchestrate_has_key_value_conflict,
    normalize_analysis_payload as orchestrate_normalize_analysis_payload,
    normalize_label_value as orchestrate_normalize_label_value,
    resolve_document_label as orchestrate_resolve_document_label,
)
from .nlp_answer_flow_orchestrator import (
    answer_rag_from_documents as orchestrate_answer_rag_from_documents,
    answer_rag_question as orchestrate_answer_rag_question,
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
from .nlp_indexing_orchestrator import (
    create_collection_name as orchestrate_create_collection_name,
    get_vector_db_collection_info as orchestrate_get_vector_db_collection_info,
    index_into_vector_db as orchestrate_index_into_vector_db,
    reset_vector_db_collection as orchestrate_reset_vector_db_collection,
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
from .nlp_style_orchestrator import (
    build_style_directives as orchestrate_build_style_directives,
    infer_answer_style as orchestrate_infer_answer_style,
    normalize_answer_style as orchestrate_normalize_answer_style,
)
from models.db_schemes import DataChunk, Project, RetrievedDocument


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
        return orchestrate_normalize_answer_style(style)

    def _infer_answer_style(self, query: Optional[str], explicit_style: Optional[str] = None) -> str:
        return orchestrate_infer_answer_style(self, query=query, explicit_style=explicit_style)

    def _build_style_directives(
        self,
        answer_style: Optional[str],
        explain_retrieval: bool,
        language: str,
    ) -> tuple[str, str]:
        return orchestrate_build_style_directives(
            self,
            answer_style=answer_style,
            explain_retrieval=explain_retrieval,
            language=language,
        )

    def create_collection_name(self, project_id: str):
        return orchestrate_create_collection_name(self, project_id=project_id)

    async def reset_vector_db_collection(self, project: Project):
        return await orchestrate_reset_vector_db_collection(self, project=project)

    async def get_vector_db_collection_info(self, project: Project):
        return await orchestrate_get_vector_db_collection_info(self, project=project)

    def _coerce_metadata_dict(self, metadata: Optional[Any]) -> Optional[Dict[str, Any]]:
        return orchestrate_coerce_metadata_dict(metadata)

    def _detect_question_type(self, query: str) -> str:
        return orchestrate_detect_question_type(query)

    def _normalize_label_value(self, value: str) -> str:
        return orchestrate_normalize_label_value(value)

    def _resolve_document_label(
        self,
        metadata: Optional[Any],
        fallback_label: str,
        asset_labels: Optional[Dict[int, str]] = None,
        asset_labels_by_name: Optional[Dict[str, str]] = None,
        asset_id_hint: Optional[int] = None,
    ) -> str:
        return orchestrate_resolve_document_label(
            self,
            metadata=metadata,
            fallback_label=fallback_label,
            asset_labels=asset_labels,
            asset_labels_by_name=asset_labels_by_name,
            asset_id_hint=asset_id_hint,
        )

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
        return await orchestrate_index_into_vector_db(
            self,
            project=project,
            chunks=chunks,
            chunks_ids=chunks_ids,
            do_reset=do_reset,
        )

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
        return await orchestrate_answer_rag_question(
            self,
            project=project,
            query=query,
            limit=limit,
            chat_messages=chat_messages,
            stream=stream,
            collector=collector,
            doc_types=doc_types,
            asset_ids=asset_ids,
            asset_labels=asset_labels,
            asset_labels_by_name=asset_labels_by_name,
            answer_style=answer_style,
            explain_retrieval=explain_retrieval,
        )

    async def answer_rag_from_documents(
        self,
        retrieved_documents: List[Any],
        query: str,
        chat_messages: Optional[List[Dict[str, str]]] = None,
        stream: bool = False,
        collector: Optional[dict] = None,
        asset_labels: Optional[Dict[int, str]] = None,
        asset_labels_by_name: Optional[Dict[str, str]] = None,
        answer_style: Optional[str] = None,
        explain_retrieval: bool = False,
        conversation_context: Optional[str] = None,
        ambiguity_threshold: Optional[float] = None,
        force_clarification: Optional[bool] = None,
    ):
        return await orchestrate_answer_rag_from_documents(
            self,
            retrieved_documents=retrieved_documents,
            query=query,
            chat_messages=chat_messages,
            stream=stream,
            collector=collector,
            asset_labels=asset_labels,
            asset_labels_by_name=asset_labels_by_name,
            answer_style=answer_style,
            explain_retrieval=explain_retrieval,
            conversation_context=conversation_context,
            ambiguity_threshold=ambiguity_threshold,
            force_clarification=force_clarification,
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
