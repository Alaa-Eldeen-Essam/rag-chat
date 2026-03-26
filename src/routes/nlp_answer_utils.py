import re
from typing import Any, Dict, List, Optional


def default_answer_metadata() -> Dict[str, Any]:
    return {
        "needs_clarification": False,
        "clarification_question": None,
        "clarification_options": None,
        "answer_confidence": None,
        "ambiguity_reason": None,
        "evidence_summary": None,
    }


def merged_answer_metadata(value: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    metadata = default_answer_metadata()
    if isinstance(value, dict):
        metadata.update(
            {
                "needs_clarification": bool(value.get("needs_clarification", False)),
                "clarification_question": value.get("clarification_question"),
                "clarification_options": value.get("clarification_options"),
                "answer_confidence": value.get("answer_confidence"),
                "ambiguity_reason": value.get("ambiguity_reason"),
                "evidence_summary": value.get("evidence_summary"),
            }
        )
    return metadata


def compose_collector_output(store: Optional[dict]) -> str:
    if not store:
        return ""
    output_text = "".join(store.get("output", [])) if isinstance(store.get("output"), list) else ""
    output_text = output_text.strip()
    if output_text:
        return output_text
    return ""


def exposed_full_prompt(value: Optional[str], *, debug_include_prompts: bool) -> Optional[str]:
    return value if debug_include_prompts else None


def exposed_chat_history(
    value: Optional[List[Dict[str, Any]]],
    *,
    debug_include_prompts: bool,
) -> List[Dict[str, Any]]:
    if debug_include_prompts and value:
        return value
    return []


def looks_like_refusal(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    patterns = [
        "لا يمكن تحديد",
        "لا توجد معلومات كافية",
        "لا أستطيع الإجابة",
        "المعلومات غير كافية",
        "cannot determine",
        "not enough information",
        "cannot be determined",
    ]
    return any(pat in t for pat in patterns)


def clean_display_hint(text: str) -> str:
    if not text:
        return ""
    value = text.strip()
    value = re.sub(r"\s+", " ", value)
    value = value.strip('\"“”\'')
    return value


def build_answer_sources(
    retrieved_documents: Optional[List[Any]],
    *,
    asset_label_lookup: Optional[Dict[int, str]] = None,
    max_sources: int = 15,
) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    seen_ids: set[int] = set()

    if not retrieved_documents:
        return sources

    for idx, doc in enumerate(retrieved_documents):
        text = getattr(doc, "text", "") or ""
        metadata = getattr(doc, "metadata", None)
        meta_dict: Dict[str, Any] = {}
        if isinstance(metadata, dict):
            meta_dict = metadata
        elif metadata is not None and hasattr(metadata, "dict"):
            try:
                maybe = metadata.dict()  # type: ignore[call-arg]
                if isinstance(maybe, dict):
                    meta_dict = maybe
            except Exception:
                meta_dict = {}

        asset_id_value = meta_dict.get("asset_id")
        asset_id_int: Optional[int] = None
        if asset_id_value is not None:
            try:
                asset_id_int = int(asset_id_value)
            except (TypeError, ValueError):
                asset_id_int = None
        file_name = (
            meta_dict.get("original_filename")
            or meta_dict.get("source_name")
            or (
                asset_label_lookup.get(int(asset_id_value))
                if asset_label_lookup and asset_id_value is not None
                else None
            )
            or f"Document {idx + 1}"
        )

        page = meta_dict.get("page") or meta_dict.get("page_number")
        section = meta_dict.get("section") or meta_dict.get("heading")
        page_no: Optional[int] = None
        try:
            if page is not None:
                page_no = int(page)
        except (TypeError, ValueError):
            page_no = None

        if page_no is not None:
            location = f"Page {page_no}"
        elif section:
            location = str(section)
        else:
            location = f"Excerpt {idx + 1}"

        chunk_id_value = meta_dict.get("chunk_id")
        key_id: int
        try:
            key_id = int(chunk_id_value) if chunk_id_value is not None else idx + 1
        except (TypeError, ValueError):
            key_id = idx + 1
        if key_id in seen_ids:
            continue
        seen_ids.add(key_id)

        snippet = (text or "").strip()
        sources.append(
            {
                "file_name": str(file_name),
                "location": location,
                "page": page_no,
                "excerpt_index": idx + 1,
                "snippet": snippet,
                "asset_id": asset_id_int,
            }
        )

        if len(sources) >= max_sources:
            break

    return sources


def should_fallback_for_low_confidence(
    answer_metadata: Optional[Dict[str, Any]],
    *,
    min_confidence: float,
) -> bool:
    if not isinstance(answer_metadata, dict):
        return False
    conf = answer_metadata.get("answer_confidence")
    if conf is None:
        return False
    try:
        confidence = float(conf)
    except (TypeError, ValueError):
        return False
    return confidence < max(0.0, min(1.0, float(min_confidence)))
