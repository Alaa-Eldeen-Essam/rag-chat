import re
from typing import Dict, List, Optional


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
    question_type = controller._detect_question_type(query)
    lowered_query = (query or "").lower()
    inferred_style = controller._infer_answer_style(query, answer_style)

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
    retrieved_documents = await controller.search_vector_db_collection(
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
    # If no such chunk exists, short-circuit with a deterministic
    # fallback answer instead of allowing the model to hallucinate a
    # time based only on partial context (e.g. generic dates in the
    # document about العربية الفصحى).
    # ------------------------------------------------------------------
    if "\u0627\u0644\u0644\u062d\u0646" in lowered_query and "\u0627\u0644\u0639\u0631\u0628" in lowered_query:
        has_supporting_chunk = False
        for doc in retrieved_documents or []:
            text_value = getattr(doc, "text", "") or ""
            t_low = text_value.lower()
            if "\u0627\u0644\u0644\u062d\u0646" in t_low and "\u0627\u0644\u0639\u0631\u0628" in t_low:
                has_supporting_chunk = True
                break

        if not has_supporting_chunk:
            fallback_answer = (
                "\u0644\u0627 \u064a\u0645\u0643\u0646 \u062a\u062d\u062f\u064a\u062f \u0645\u062a\u0649 \u0634\u0627\u0639 \u0627\u0644\u0644\u062d\u0646 \u0628\u064a\u0646 \u0627\u0644\u0639\u0631\u0628 \u0645\u0646 \u0627\u0644\u0645\u0633\u062a\u0646\u062f\u0627\u062a \u0627\u0644\u0645\u0641\u0647\u0631\u0633\u0629 \u0627\u0644\u062d\u0627\u0644\u064a\u0629."
            )
            return fallback_answer, None, None

    direct_hint = controller._try_extract_direct_answer(
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
            doc_label_for_hint = controller._resolve_document_label(
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
            prefix_ar = f'\u0648\u0641\u0642\u0627\u064b \u0644\u0644\u0645\u0633\u062a\u0646\u062f "{doc_label_for_hint}"\u060c '
            prefix_en = f'According to the document "{doc_label_for_hint}", '
        else:
            prefix_ar = "\u0648\u0641\u0642\u0627\u064b \u0644\u0644\u0645\u0633\u062a\u0646\u062f\u0627\u062a\u060c "
            prefix_en = "According to the documents, "

        if has_arabic:
            answer_text = f"{prefix_ar}\u0643\u0627\u0646 \u0630\u0644\u0643 \u0641\u064a {direct_hint}."
        else:
            answer_text = f"{prefix_en}this occurred on {direct_hint}."
        metadata = controller._default_answer_metadata()
        metadata["answer_confidence"] = 1.0
        return answer_text, None, None, metadata

    return await controller.generate_rag_answer_from_documents(
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
