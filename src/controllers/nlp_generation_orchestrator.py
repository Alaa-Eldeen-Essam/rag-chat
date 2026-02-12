import logging
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def generate_multihop_rag_answer(
    controller,
    project,
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
    max_hops = max(1, min(max_hops or 2, 5))
    per_hop_k = max(1, min(per_hop_k or 6, 20))
    per_hop_evidence = max(1, min(per_hop_evidence or 3, per_hop_k))
    hop_history_weight = controller._clamp_unit(
        history_weight,
        getattr(controller.app_settings, "RAG_HISTORY_WEIGHT", 0.75),
    )
    inferred_style = controller._infer_answer_style(query, answer_style)

    template_language = getattr(controller.template_parser, "language", "en")
    style_instructions, _ = controller._build_style_directives(
        answer_style=inferred_style,
        explain_retrieval=False,
        language=template_language,
    )
    system_prompt = controller.template_parser.get(
        "multihop",
        "system_prompt",
        {"style_instructions": style_instructions},
    )

    hop_notes: List[str] = []
    aggregated_evidence: List[Any] = []
    context_text = (conversation_context or controller.build_conversation_context(chat_messages)).strip()
    scope_map: Dict[int, Optional[List[int]]] = {}
    if project_asset_scope:
        for pid, scoped_asset_ids in project_asset_scope.items():
            try:
                pid_int = int(pid)
            except (TypeError, ValueError):
                continue
            cleaned_asset_ids: List[int] = []
            for asset_id in scoped_asset_ids or []:
                try:
                    cleaned_asset_ids.append(int(asset_id))
                except (TypeError, ValueError):
                    continue
            scope_map[pid_int] = cleaned_asset_ids or None

    if not scope_map:
        try:
            fallback_project_id = int(getattr(project, "project_id"))
        except (TypeError, ValueError):
            fallback_project_id = getattr(project, "project_id")
        scope_map[fallback_project_id] = list(asset_ids) if asset_ids else None

    for hop_idx in range(max_hops):
        query_only_parts: List[str] = []
        if query:
            query_only_parts.append(query)
        if hop_notes:
            query_only_parts.append(" ".join(hop_notes[-2:]))
        query_only_text = "\n".join([part for part in query_only_parts if part]).strip()
        if not query_only_text:
            break
        history_aware_text = query_only_text
        if context_text:
            history_aware_text = f"{context_text}\n\n{query_only_text}".strip()

        query_only_results: List[Any] = []
        history_aware_results: List[Any] = []
        for scope_project_id, scope_asset_ids in scope_map.items():
            project_stub = SimpleNamespace(project_id=scope_project_id)
            scoped_query_results = await controller.search_vector_db_collection(
                project=project_stub,
                text=query_only_text,
                limit=per_hop_k,
                doc_types=doc_types,
                asset_ids=scope_asset_ids,
            )
            if scoped_query_results:
                query_only_results.extend(scoped_query_results)

            if history_aware_text == query_only_text:
                if scoped_query_results:
                    history_aware_results.extend(scoped_query_results)
                continue

            scoped_history_results = await controller.search_vector_db_collection(
                project=project_stub,
                text=history_aware_text,
                limit=per_hop_k,
                doc_types=doc_types,
                asset_ids=scope_asset_ids,
            )
            if scoped_history_results:
                history_aware_results.extend(scoped_history_results)

        retrieved = controller.fuse_query_and_history_results(
            query_only_docs=query_only_results or [],
            history_aware_docs=history_aware_results or [],
            limit=per_hop_k,
            history_weight=hop_history_weight,
        )

        logger.info(
            "MULTIHOP_RETRIEVAL_FUSION hop=%d query_only=%d history_aware=%d fused=%d history_weight=%.3f",
            hop_idx + 1,
            len(query_only_results or []),
            len(history_aware_results or []),
            len(retrieved or []),
            hop_history_weight,
        )

        if not retrieved:
            break

        top_evidence = list(retrieved[:per_hop_evidence])
        aggregated_evidence.extend(top_evidence)

        snippets: List[str] = []
        for doc in top_evidence:
            txt = (getattr(doc, "text", "") or "").strip()
            if txt:
                snippets.append(txt[:700])
        evidence_text = "\n\n".join(snippets)

        hop_summary_prompt = controller.template_parser.get(
            "multihop",
            "hop_summary_prompt",
            {
                "hop_index": hop_idx + 1,
                "query": query,
                "evidence_text": evidence_text,
            },
        )

        hop_history = [
            controller.generation_client.construct_prompt(
                prompt=system_prompt,
                role=controller.generation_client.enums.SYSTEM.value,
            )
        ]

        hop_summary = controller.generation_client.generate_text(
            prompt=hop_summary_prompt,
            chat_history=hop_history,
            temperature=generation_temperature if generation_temperature is not None else 0.0,
        )

        hop_summary = (hop_summary or "").strip()
        if hop_summary:
            hop_notes.append(hop_summary)
        else:
            hop_notes.append("")

        if any(trigger in hop_summary.lower() for trigger in ["answer:", "الجواب", "الإجابة"]):
            break

    pseudo_docs: List[Any] = []
    for idx, note in enumerate(hop_notes):
        if not note:
            continue
        pseudo_docs.append(
            SimpleNamespace(
                text=note,
                metadata={"doc_label": f"Hop {idx + 1} summary"},
            )
        )

    final_docs = list(aggregated_evidence) + pseudo_docs

    if not final_docs:
        return None, None, None, [], controller._default_answer_metadata()

    answer_result, full_prompt, chat_history, answer_metadata = await controller.generate_rag_answer_from_documents(
        retrieved_documents=final_docs,
        query=query,
        chat_messages=chat_messages,
        stream=stream,
        collector=collector,
        asset_labels=None,
        asset_labels_by_name=None,
        direct_hint=None,
        answer_style=inferred_style,
        explain_retrieval=False,
        template_group="multihop",
        conversation_context=conversation_context,
        ambiguity_threshold=ambiguity_threshold,
        force_clarification=force_clarification,
    )

    return answer_result, full_prompt, chat_history, final_docs, answer_metadata


async def generate_rag_answer_from_documents(
    controller,
    retrieved_documents: List[Any],
    query: str,
    chat_messages: Optional[List[Dict[str, str]]] = None,
    stream: bool = False,
    collector: Optional[dict] = None,
    asset_labels: Optional[Dict[int, str]] = None,
    asset_labels_by_name: Optional[Dict[str, str]] = None,
    direct_hint: Optional[str] = None,
    answer_style: Optional[str] = None,
    explain_retrieval: bool = False,
    template_group: str = "rag",
    conversation_context: Optional[str] = None,
    ambiguity_threshold: Optional[float] = None,
    force_clarification: Optional[bool] = None,
):
    answer_or_stream, full_prompt, chat_history = None, None, None
    answer_metadata = controller._default_answer_metadata()

    if not retrieved_documents or len(retrieved_documents) == 0:
        return answer_or_stream, full_prompt, chat_history, answer_metadata

    template_language = getattr(controller.template_parser, "language", "en")
    context_text = conversation_context or controller.build_conversation_context(chat_messages)
    style_instructions, style_hint = controller._build_style_directives(
        answer_style=answer_style,
        explain_retrieval=explain_retrieval,
        language=template_language,
    )

    system_prompt = controller.template_parser.get(
        template_group,
        "system_prompt",
        {"style_instructions": style_instructions},
    )

    evidence_documents: List[Any] = list(retrieved_documents)

    analysis = await controller.analyze_evidence_for_answer(
        query=query,
        retrieved_documents=evidence_documents,
        chat_messages=chat_messages,
        conversation_context=context_text,
        template_group=template_group,
        ambiguity_threshold=ambiguity_threshold,
        asset_labels=asset_labels,
        asset_labels_by_name=asset_labels_by_name,
    )

    ambiguity_enabled = bool(getattr(controller.app_settings, "RAG_AMBIGUITY_ENABLED", True))
    force_clarify = (
        bool(getattr(controller.app_settings, "RAG_FORCE_CLARIFICATION", True))
        if force_clarification is None
        else bool(force_clarification)
    )
    needs_clarification = bool(analysis.get("ambiguity_detected", False) and ambiguity_enabled)

    answer_metadata.update(
        {
            "needs_clarification": bool(needs_clarification and force_clarify),
            "clarification_question": analysis.get("clarification_question") or None,
            "clarification_options": analysis.get("clarification_options") or None,
            "answer_confidence": analysis.get("answer_confidence"),
            "ambiguity_reason": analysis.get("ambiguity_reason") or None,
            "evidence_summary": analysis.get("evidence_summary") or None,
            "_analysis_parse_failed": bool(analysis.get("__analysis_parse_failed", False)),
            "_analysis_source": analysis.get("__analysis_source"),
        }
    )

    logger.info(
        "RAG_AMBIGUITY_EVENT mode=%s ambiguity_detected=%s needs_clarification=%s force_clarification=%s reason=%s candidates=%d parse_failed=%s",
        template_group,
        bool(analysis.get("ambiguity_detected", False) and ambiguity_enabled),
        bool(needs_clarification and force_clarify),
        bool(force_clarify),
        str(analysis.get("ambiguity_reason") or "").strip(),
        len(analysis.get("candidate_answers") or []),
        bool(analysis.get("__analysis_parse_failed", False)),
    )

    if needs_clarification and force_clarify:
        clarification_question = (
            str(analysis.get("clarification_question") or "").strip()
            or ("Could you clarify which exact option you mean?")
        )
        options = analysis.get("clarification_options") or []
        option_lines = [
            f"- {str(option).strip()}"
            for option in options
            if str(option).strip()
        ]
        if option_lines:
            clarification_text = "\n".join([clarification_question, *option_lines])
        else:
            clarification_text = clarification_question
        return clarification_text, None, None, answer_metadata

    document_sections = []
    for idx, doc in enumerate(evidence_documents):
        chunk_text = controller.generation_client.process_text(doc.text)
        doc_label = controller._resolve_document_label(
            getattr(doc, "metadata", None),
            fallback_label=f"Document {idx + 1}",
            asset_labels=asset_labels,
            asset_labels_by_name=asset_labels_by_name,
        )
        section = controller.template_parser.get(template_group, "document_prompt", {
                "doc_label": doc_label,
                "chunk_text": chunk_text,
        }) or f"## Document: {doc_label}\n### Content: {chunk_text}"
        document_sections.append(section)

    documents_prompts = "\n".join(document_sections)

    hint_section = ""
    if direct_hint:
        hint_section = controller.template_parser.get(template_group, "hint_section", {
            "hint": direct_hint,
        }) or ("\n\n# Direct candidate answer extracted from documents:\n"
               f"{direct_hint}\n")
        documents_prompts = documents_prompts + "\n" + hint_section

    footer_prompt = controller.template_parser.get(template_group, "footer_prompt", {
        "query": query,
        "style_hint": style_hint,
        "conversation_context": context_text or "",
        "analysis_summary": analysis.get("evidence_summary") or "",
    })

    chat_history = [
        controller.generation_client.construct_prompt(
            prompt=system_prompt,
            role=controller.generation_client.enums.SYSTEM.value,
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
                controller.generation_client.construct_prompt(
                    prompt=controller.generation_client.process_text(message.get("prompt", "")),
                    role=controller.generation_client.enums.USER.value,
                )
            )
            chat_history.append(
                controller.generation_client.construct_prompt(
                    prompt=controller.generation_client.process_text(message.get("answer", "")),
                    role=controller.generation_client.enums.ASSISTANT.value,
                )
            )

        for message in prioritized_messages:
            chat_history.append(
                controller.generation_client.construct_prompt(
                    prompt=controller.generation_client.process_text(message.get("prompt", "")),
                    role=controller.generation_client.enums.USER.value,
                )
            )
            chat_history.append(
                controller.generation_client.construct_prompt(
                    prompt=controller.generation_client.process_text(message.get("answer", "")),
                    role=controller.generation_client.enums.ASSISTANT.value,
                )
            )

    full_prompt = "\n\n".join([ documents_prompts,  footer_prompt])

    if stream:
        answer_or_stream = controller.generation_client.generate_text_stream(
            prompt=full_prompt,
            chat_history=chat_history,
            collector=collector
        )
    else:
        answer_or_stream = controller.generation_client.generate_text(
            prompt=full_prompt,
            chat_history=chat_history
        )

    return answer_or_stream, full_prompt, chat_history, answer_metadata


async def generate_regular_chat_response(
    controller,
    query: str,
    chat_messages: Optional[List[Dict[str, str]]] = None,
    stream: bool = False,
    collector: Optional[dict] = None,
    answer_style: Optional[str] = None,
    explain_retrieval: bool = False,  # kept for API symmetry
):
    system_prompt = controller.template_parser.get("chat", "system_prompt") or (
        "You are a concise, policy-compliant assistant. "
        "Answer helpfully, stay polite, and decline any unsafe requests."
    )
    template_language = getattr(controller.template_parser, "language", "en")
    _, style_hint = controller._build_style_directives(
        answer_style=answer_style,
        explain_retrieval=False,
        language=template_language,
    )

    chat_history = [
        controller.generation_client.construct_prompt(
            prompt=system_prompt,
            role=controller.generation_client.enums.SYSTEM.value,
        )
    ]

    if chat_messages:
        trimmed_messages = chat_messages[-8:]
        for message in trimmed_messages:
            prompt_text = controller.generation_client.process_text(message.get("prompt", ""))
            answer_text = controller.generation_client.process_text(message.get("answer", ""))
            if prompt_text:
                chat_history.append(
                    controller.generation_client.construct_prompt(
                        prompt=prompt_text,
                        role=controller.generation_client.enums.USER.value,
                    )
                )
            if answer_text:
                chat_history.append(
                    controller.generation_client.construct_prompt(
                        prompt=answer_text,
                        role=controller.generation_client.enums.ASSISTANT.value,
                    )
                )

    style_prefix = ""
    style_norm = controller._normalize_answer_style(answer_style)
    if style_norm == "detailed":
        style_prefix = "Provide a detailed, well-structured answer. "
    elif style_norm == "balanced":
        style_prefix = "Provide a concise answer, then add key details. "
    else:
        style_prefix = "Keep the answer concise and direct. "

    final_prompt = controller.generation_client.process_text(f"{style_prefix}{query or ''}".strip())
    if stream:
        answer_stream = controller.generation_client.generate_text_stream(
            prompt=final_prompt,
            chat_history=chat_history,
            collector=collector,
        )
        return answer_stream, final_prompt, chat_history

    answer = controller.generation_client.generate_text(
        prompt=final_prompt,
        chat_history=chat_history,
    )
    return answer, final_prompt, chat_history


def summarize_chunks(
    controller,
    chunks: List[Any],
    focus: Optional[str] = None,
    max_output_tokens: Optional[int] = None,
    asset_labels: Optional[Dict[int, str]] = None,
    asset_labels_by_name: Optional[Dict[str, str]] = None,
    stream: bool = False,
    collector: Optional[Dict[str, list]] = None,
):
    if not chunks or len(chunks) == 0:
        return None, None

    system_prompt = controller.template_parser.get("summary", "system_prompt") or (
        "You are an assistant that condenses provided content into a clear, concise summary."
    )

    document_sections = []
    for idx, chunk in enumerate(chunks):
        chunk_text = controller.generation_client.process_text(chunk.chunk_text)
        fallback_label = f"Document {chunk.chunk_order if chunk.chunk_order else idx + 1}"
        doc_label = controller._resolve_document_label(
            getattr(chunk, "chunk_metadata", None),
            fallback_label=fallback_label,
            asset_labels=asset_labels,
            asset_labels_by_name=asset_labels_by_name,
            asset_id_hint=getattr(chunk, "chunk_asset_id", None),
        )
        section = controller.template_parser.get("summary", "document_prompt", {
            "doc_label": doc_label,
            "chunk_text": chunk_text,
        }) or f"## Document: {doc_label}\n{chunk_text}"
        document_sections.append(section)

    documents_prompts = "\n".join(document_sections)

    default_focus = controller.template_parser.get("summary", "default_focus") or "Provide a concise summary that highlights the key ideas and critical details."

    summary_prompt = controller.template_parser.get("summary", "summary_prompt", {
        "documents": documents_prompts,
        "focus": focus or default_focus,
    }) or "\n".join([
        "Summarize the following documents.",
        documents_prompts,
        "",
        focus or default_focus
    ])

    chat_history = [
        controller.generation_client.construct_prompt(
            prompt=system_prompt,
            role=controller.generation_client.enums.SYSTEM.value,
        )
    ]

    if stream:
        summary_stream = controller.generation_client.generate_text_stream(
            prompt=summary_prompt,
            chat_history=chat_history,
            max_output_tokens=max_output_tokens,
            collector=collector,
        )
        return summary_stream, summary_prompt

    summary = controller.generation_client.generate_text(
        prompt=summary_prompt,
        chat_history=chat_history,
        max_output_tokens=max_output_tokens
    )

    return summary, summary_prompt
