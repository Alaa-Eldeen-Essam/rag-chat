from typing import Any, Dict, List, Optional

from helpers.answer_safety import (
    build_when_direct_answer,
    has_lahn_arab_support,
    is_direct_hint_supported,
)


async def answer_rag_question(
    controller,
    project,
    query: str,
    limit: int = 10,
    chat_messages: Optional[List[Dict[str, str]]] = None,
    stream: bool = False,
    collector: Optional[dict] = None,
    doc_types: Optional[List[str]] = None,
    asset_ids: Optional[List[int]] = None,
    asset_labels: Optional[Dict[int, str]] = None,
    asset_labels_by_name: Optional[Dict[str, str]] = None,
    answer_style: Optional[str] = None,
    explain_retrieval: bool = False,
):
    # Build an augmented retrieval query that incorporates recent
    # conversation turns (if any) so that follow-up questions using
    # pronouns like "there" still retrieve the right chunks.
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

    retrieved_documents = await controller.search_vector_db_collection(
        project=project,
        text=retrieval_text,
        limit=limit,
        doc_types=doc_types,
        asset_ids=asset_ids,
    )

    return await answer_rag_from_documents(
        controller=controller,
        retrieved_documents=retrieved_documents or [],
        query=query,
        chat_messages=chat_messages,
        stream=stream,
        collector=collector,
        asset_labels=asset_labels,
        asset_labels_by_name=asset_labels_by_name,
        answer_style=answer_style,
        explain_retrieval=explain_retrieval,
    )


async def answer_rag_from_documents(
    controller,
    retrieved_documents: Optional[List[Any]],
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
    documents = retrieved_documents or []
    question_type = controller._detect_question_type(query)
    lowered_query = (query or "").lower()
    inferred_style = controller._infer_answer_style(query, answer_style)

    if "\u0627\u0644\u0644\u062d\u0646" in lowered_query and "\u0627\u0644\u0639\u0631\u0628" in lowered_query:
        if not has_lahn_arab_support(documents):
            fallback_answer = (
                "\u0644\u0627 \u064a\u0645\u0643\u0646 \u062a\u062d\u062f\u064a\u062f \u0645\u062a\u0649 \u0634\u0627\u0639 \u0627\u0644\u0644\u062d\u0646 \u0628\u064a\u0646 \u0627\u0644\u0639\u0631\u0628 \u0645\u0646 \u0627\u0644\u0645\u0633\u062a\u0646\u062f\u0627\u062a \u0627\u0644\u0645\u0641\u0647\u0631\u0633\u0629 \u0627\u0644\u062d\u0627\u0644\u064a\u0629."
            )
            metadata = controller._default_answer_metadata()
            metadata.update(
                {
                    "_question_type": question_type,
                    "_direct_hint": None,
                    "_doc_label_for_hint": None,
                }
            )
            return fallback_answer, "", [], metadata

    direct_hint = controller._try_extract_direct_answer(
        query=query,
        documents=documents,
        question_type=question_type,
    )

    doc_label_for_hint: Optional[str] = None
    if direct_hint and documents:
        chosen_doc = None
        for doc in documents:
            text_value = getattr(doc, "text", "") or ""
            if direct_hint in text_value:
                chosen_doc = doc
                break
        if chosen_doc is None:
            chosen_doc = documents[0]

        try:
            doc_label_for_hint = controller._resolve_document_label(
                getattr(chosen_doc, "metadata", None),
                fallback_label="Document 1",
                asset_labels=asset_labels,
                asset_labels_by_name=asset_labels_by_name,
            )
        except Exception:
            doc_label_for_hint = None

    if direct_hint and question_type == "when":
        direct_hint_supported = is_direct_hint_supported(
            query=query,
            direct_hint=direct_hint,
            documents=documents,
        )
        if not direct_hint_supported:
            direct_hint = None

    if direct_hint and question_type == "when" and not stream:
        answer_text = build_when_direct_answer(
            query=query,
            direct_hint=direct_hint,
            doc_label_for_hint=doc_label_for_hint,
        )
        metadata = controller._default_answer_metadata()
        metadata["answer_confidence"] = 1.0
        metadata.update(
            {
                "_question_type": question_type,
                "_direct_hint": direct_hint,
                "_doc_label_for_hint": doc_label_for_hint,
            }
        )
        return answer_text, None, None, metadata

    answer_result, full_prompt, chat_history, answer_metadata = await controller.generate_rag_answer_from_documents(
        retrieved_documents=documents,
        query=query,
        chat_messages=chat_messages,
        stream=stream,
        collector=collector,
        asset_labels=asset_labels,
        asset_labels_by_name=asset_labels_by_name,
        direct_hint=direct_hint,
        answer_style=inferred_style,
        explain_retrieval=explain_retrieval,
        conversation_context=conversation_context,
        ambiguity_threshold=ambiguity_threshold,
        force_clarification=force_clarification,
    )

    if not isinstance(answer_metadata, dict):
        answer_metadata = controller._default_answer_metadata()
    answer_metadata.update(
        {
            "_question_type": question_type,
            "_direct_hint": direct_hint,
            "_doc_label_for_hint": doc_label_for_hint,
        }
    )

    return answer_result, full_prompt, chat_history, answer_metadata
