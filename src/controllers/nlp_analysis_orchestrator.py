import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

EVIDENCE_DOC_LIMIT = 5
EVIDENCE_CHAR_BUDGET = 4000


def coerce_metadata_dict(metadata: Optional[Any]) -> Optional[Dict[str, Any]]:
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


def normalize_label_value(value: str) -> str:
    label = (value or "").strip()
    if not label:
        return ""
    normalized = label.replace("\\", "/")
    if "/" in normalized:
        normalized = normalized.split("/")[-1]
    return normalized


def resolve_document_label(
    controller,
    metadata: Optional[Any],
    fallback_label: str,
    asset_labels: Optional[Dict[int, str]] = None,
    asset_labels_by_name: Optional[Dict[str, str]] = None,
    asset_id_hint: Optional[int] = None,
) -> str:
    metadata_dict = coerce_metadata_dict(metadata)

    candidate_asset_id = asset_id_hint
    if candidate_asset_id is None and metadata_dict:
        candidate_asset_id = metadata_dict.get("asset_id")

    if asset_labels and candidate_asset_id is not None:
        try:
            label = asset_labels.get(int(candidate_asset_id))
        except (ValueError, TypeError):
            label = None
        if label:
            return normalize_label_value(label)

    if metadata_dict:
        for key in ("source_name", "original_filename", "original_name", "filename", "name", "source"):
            value = metadata_dict.get(key)
            if isinstance(value, str):
                cleaned = normalize_label_value(value)
                if cleaned:
                    if asset_labels_by_name and cleaned in asset_labels_by_name:
                        return asset_labels_by_name[cleaned]
                    return cleaned

    return normalize_label_value(fallback_label)


def default_answer_metadata(controller) -> Dict[str, Any]:
    return {
        "needs_clarification": False,
        "clarification_question": None,
        "clarification_options": None,
        "answer_confidence": None,
        "ambiguity_reason": None,
        "evidence_summary": None,
    }


def extract_json_object(controller, text: Optional[str]) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    raw = text.strip()
    if not raw:
        return None

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    candidate = raw[start : end + 1]
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return None
    return None


def normalize_analysis_payload(
    controller,
    payload: Optional[Dict[str, Any]],
    query: str,
) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {
        "resolved_question": query,
        "evidence_facts": [],
        "candidate_answers": [],
        "ambiguity_detected": False,
        "ambiguity_reason": "",
        "clarification_question": "",
        "clarification_options": [],
        "answer_confidence": 0.0,
    }
    if not payload:
        return normalized

    resolved_question = payload.get("resolved_question")
    if isinstance(resolved_question, str) and resolved_question.strip():
        normalized["resolved_question"] = resolved_question.strip()

    facts = payload.get("evidence_facts")
    if isinstance(facts, list):
        cleaned_facts = []
        for item in facts:
            if not isinstance(item, dict):
                continue
            fact_text = str(item.get("fact") or "").strip()
            if not fact_text:
                continue
            support = item.get("support")
            if not isinstance(support, list):
                support = []
            support = [str(s).strip() for s in support if str(s).strip()]
            confidence = controller._clamp_unit(item.get("confidence"), 0.5)
            cleaned_facts.append(
                {
                    "fact": fact_text,
                    "support": support,
                    "confidence": confidence,
                }
            )
        normalized["evidence_facts"] = cleaned_facts

    candidates = payload.get("candidate_answers")
    if isinstance(candidates, list):
        cleaned_candidates = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            answer_text = str(item.get("answer") or "").strip()
            if not answer_text:
                continue
            support_count_raw = item.get("support_count")
            try:
                support_count = int(support_count_raw) if support_count_raw is not None else 0
            except (TypeError, ValueError):
                support_count = 0
            confidence = controller._clamp_unit(item.get("confidence"), 0.5)
            cleaned_candidates.append(
                {
                    "answer": answer_text,
                    "support_count": max(0, support_count),
                    "confidence": confidence,
                }
            )
        cleaned_candidates.sort(key=lambda rec: rec.get("confidence", 0.0), reverse=True)
        normalized["candidate_answers"] = cleaned_candidates

    normalized["ambiguity_detected"] = bool(payload.get("ambiguity_detected", False))
    ambiguity_reason = payload.get("ambiguity_reason")
    if isinstance(ambiguity_reason, str):
        normalized["ambiguity_reason"] = ambiguity_reason.strip()
    clarification_question = payload.get("clarification_question")
    if isinstance(clarification_question, str):
        normalized["clarification_question"] = clarification_question.strip()
    clarification_options = payload.get("clarification_options")
    if isinstance(clarification_options, list):
        normalized["clarification_options"] = [
            str(option).strip() for option in clarification_options if str(option).strip()
        ]

    top_confidence = 0.0
    if normalized["candidate_answers"]:
        top_confidence = float(normalized["candidate_answers"][0].get("confidence") or 0.0)
    normalized["answer_confidence"] = controller._clamp_unit(
        payload.get("answer_confidence"),
        top_confidence,
    )

    return normalized


def build_heuristic_analysis(
    controller,
    query: str,
    documents: List[Any],
    asset_labels: Optional[Dict[int, str]] = None,
    asset_labels_by_name: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    heuristic = normalize_analysis_payload(controller, {}, query)
    facts: List[Dict[str, Any]] = []
    candidates: List[Dict[str, Any]] = []
    max_docs = min(4, len(documents))

    for idx, doc in enumerate(documents[:max_docs]):
        text_value = (getattr(doc, "text", "") or "").strip()
        if not text_value:
            continue

        doc_label = controller._resolve_document_label(
            getattr(doc, "metadata", None),
            fallback_label=f"Document {idx + 1}",
            asset_labels=asset_labels,
            asset_labels_by_name=asset_labels_by_name,
        )
        snippet = re.sub(r"\s+", " ", text_value)[:220].strip()
        score = controller._clamp_unit(getattr(doc, "score", None), 0.5)
        facts.append({"fact": snippet, "support": [doc_label], "confidence": score})
        candidates.append(
            {"answer": snippet, "support_count": 1, "confidence": score}
        )

    heuristic["evidence_facts"] = facts
    candidates.sort(key=lambda rec: rec["confidence"], reverse=True)
    heuristic["candidate_answers"] = candidates
    heuristic["answer_confidence"] = candidates[0]["confidence"] if candidates else 0.0
    return heuristic


def build_evidence_summary(controller, analysis: Dict[str, Any]) -> str:
    facts = analysis.get("evidence_facts") or []
    if not isinstance(facts, list) or not facts:
        candidates = analysis.get("candidate_answers") or []
        if isinstance(candidates, list) and candidates:
            top = candidates[0].get("answer")
            if isinstance(top, str) and top.strip():
                return top.strip()
        return ""

    lines: List[str] = []
    for fact in facts[:4]:
        if not isinstance(fact, dict):
            continue
        fact_text = str(fact.get("fact") or "").strip()
        if not fact_text:
            continue
        support = fact.get("support")
        support_str = ""
        if isinstance(support, list) and support:
            support_str = f" ({', '.join([str(s) for s in support[:2]])})"
        lines.append(f"- {fact_text}{support_str}")
    return "\n".join(lines).strip()


def extract_conflict_signatures(controller, text: str) -> List[Tuple[str, str]]:
    content = str(text or "").strip()
    if not content:
        return []

    signatures: List[Tuple[str, str]] = []
    lower = content.lower()

    for match in re.findall(r"\b\d{1,4}[-/]\d{1,2}[-/]\d{1,4}\b", lower):
        signatures.append(("date", match))
    for match in re.findall(r"\b(19|20)\d{2}\b", lower):
        signatures.append(("year", match))

    for match in re.findall(r"\b\d+(?:[.,]\d+)?\b", lower):
        signatures.append(("number", match.replace(",", "")))

    for match in re.findall(r"[\"'��]([^\"'��]{2,80})[\"'��]", content):
        cleaned = re.sub(r"\s+", " ", match).strip().lower()
        if cleaned and not re.search(r"\d", cleaned):
            signatures.append(("name", cleaned))

    latin_name_match = re.search(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", content)
    if latin_name_match:
        signatures.append(("name", latin_name_match.group(0).strip().lower()))

    arabic_name_match = re.search(r"[\u0600-\u06FF]{2,}(?:\s+[\u0600-\u06FF]{2,})+", content)
    if arabic_name_match:
        signatures.append(("name", arabic_name_match.group(0).strip().lower()))

    unique: List[Tuple[str, str]] = []
    seen = set()
    for sig in signatures:
        if sig in seen:
            continue
        seen.add(sig)
        unique.append(sig)
    return unique


def has_key_value_conflict(
    controller,
    analysis: Dict[str, Any],
    threshold: float,
    top_conf: float,
) -> bool:
    typed_values: Dict[str, set[str]] = {
        "date": set(),
        "year": set(),
        "number": set(),
        "name": set(),
    }

    candidates = analysis.get("candidate_answers") or []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        conf = float(candidate.get("confidence") or 0.0)
        if conf < max(0.0, top_conf - threshold):
            continue
        text = str(candidate.get("answer") or "").strip()
        for sig_type, sig_value in extract_conflict_signatures(controller, text):
            typed_values.setdefault(sig_type, set()).add(sig_value)

    facts = analysis.get("evidence_facts") or []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        conf = controller._clamp_unit(fact.get("confidence"), 0.5)
        if conf < max(0.0, top_conf - threshold):
            continue
        text = str(fact.get("fact") or "").strip()
        for sig_type, sig_value in extract_conflict_signatures(controller, text):
            typed_values.setdefault(sig_type, set()).add(sig_value)

    return any(len(values) > 1 for values in typed_values.values())


def compact_clarification_option(controller, text: str, max_len: int = 90) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return ""

    parts = re.split(r"[\.!\?\u061f\u061b\n]+", value)
    for part in parts:
        cleaned = part.strip()
        if cleaned:
            value = cleaned
            break

    if len(value) > max_len:
        value = value[: max_len - 3].rstrip() + "..."
    return value


def derive_clarification_option(controller, answer_text: str) -> str:
    value = str(answer_text or "").strip()
    if not value:
        return ""

    signatures = extract_conflict_signatures(controller, value)
    for sig_type, sig_value in signatures:
        if sig_type in {"date", "year", "number", "name"} and sig_value:
            return compact_clarification_option(controller, sig_value, max_len=60)
    return compact_clarification_option(controller, value)


def apply_ambiguity_gate(
    controller,
    analysis: Dict[str, Any],
    query: str,
    ambiguity_threshold: Optional[float],
    top_n: Optional[int],
) -> Dict[str, Any]:
    threshold = controller._clamp_unit(
        ambiguity_threshold,
        getattr(controller.app_settings, "RAG_AMBIGUITY_THRESHOLD", 0.12),
    )
    configured_top_n = top_n or getattr(controller.app_settings, "RAG_AMBIGUITY_TOP_N", 4)
    try:
        configured_top_n = int(configured_top_n)
    except (TypeError, ValueError):
        configured_top_n = 4
    configured_top_n = max(2, min(configured_top_n, 10))

    candidates = analysis.get("candidate_answers")
    if not isinstance(candidates, list):
        candidates = []
    candidates = sorted(
        [c for c in candidates if isinstance(c, dict)],
        key=lambda rec: float(rec.get("confidence") or 0.0),
        reverse=True,
    )
    analysis["candidate_answers"] = candidates

    top_conf = float(candidates[0].get("confidence") or 0.0) if candidates else 0.0
    second_conf = float(candidates[1].get("confidence") or 0.0) if len(candidates) > 1 else 0.0
    confidence_gap = top_conf - second_conf

    conflict_pool = candidates[:configured_top_n]
    unique_top_answers = {
        str(item.get("answer") or "").strip().lower()
        for item in conflict_pool
        if str(item.get("answer") or "").strip()
        and float(item.get("confidence") or 0.0) >= max(0.0, top_conf - threshold)
    }
    competing_candidates = len(unique_top_answers) > 1
    weak_separation = len(candidates) > 1 and confidence_gap <= threshold
    key_value_conflict = has_key_value_conflict(
        controller,
        analysis=analysis,
        threshold=threshold,
        top_conf=top_conf,
    )

    ambiguity_detected = bool(analysis.get("ambiguity_detected", False))
    if competing_candidates or weak_separation or key_value_conflict:
        ambiguity_detected = True

    if ambiguity_detected and not str(analysis.get("ambiguity_reason") or "").strip():
        if weak_separation:
            analysis["ambiguity_reason"] = "Multiple candidates have close confidence scores."
        elif key_value_conflict:
            analysis["ambiguity_reason"] = (
                "Evidence contains conflicting key values (such as dates, numbers, or names)."
            )
        elif competing_candidates:
            analysis["ambiguity_reason"] = "Multiple evidence sections support different plausible answers."
        else:
            analysis["ambiguity_reason"] = "Evidence appears ambiguous."

    if ambiguity_detected:
        clarification_question = str(analysis.get("clarification_question") or "").strip()
        if not clarification_question:
            has_arabic = bool(re.search(r"[\u0600-\u06FF]", query or ""))
            clarification_question = (
                "\u0647\u0644 \u064a\u0645\u0643\u0646\u0643 \u062a\u062d\u062f\u064a\u062f \u0623\u064a \u062e\u064a\u0627\u0631 \u062a\u0642\u0635\u062f\u0647 \u0628\u062f\u0642\u0629\u061f"
                if has_arabic
                else "Could you clarify which exact option you mean?"
            )
            analysis["clarification_question"] = clarification_question

        options = analysis.get("clarification_options")
        if not isinstance(options, list):
            options = []
        cleaned_options = [
            compact_clarification_option(controller, str(opt))
            for opt in options
            if compact_clarification_option(controller, str(opt))
        ]
        if not cleaned_options:
            for item in conflict_pool:
                value = derive_clarification_option(
                    controller,
                    str(item.get("answer") or "").strip(),
                )
                if value and value not in cleaned_options:
                    cleaned_options.append(value)
                if len(cleaned_options) >= 4:
                    break
        analysis["clarification_options"] = cleaned_options

    analysis["ambiguity_detected"] = ambiguity_detected
    analysis["answer_confidence"] = controller._clamp_unit(
        analysis.get("answer_confidence"),
        top_conf,
    )
    analysis["evidence_summary"] = build_evidence_summary(controller, analysis)
    return analysis


async def analyze_evidence_for_answer(
    controller,
    query: str,
    retrieved_documents: List[Any],
    chat_messages: Optional[List[Dict[str, str]]] = None,
    conversation_context: Optional[str] = None,
    template_group: str = "rag",
    ambiguity_threshold: Optional[float] = None,
    asset_labels: Optional[Dict[int, str]] = None,
    asset_labels_by_name: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    if not retrieved_documents:
        analysis = normalize_analysis_payload(controller, {}, query)
        analysis["evidence_summary"] = ""
        analysis["__analysis_source"] = "empty"
        analysis["__analysis_parse_failed"] = False
        return analysis

    max_docs = getattr(controller.app_settings, "RAG_EVIDENCE_SYNTHESIS_MAX_DOCS", EVIDENCE_DOC_LIMIT)
    try:
        max_docs = int(max_docs)
    except (TypeError, ValueError):
        max_docs = EVIDENCE_DOC_LIMIT
    max_docs = max(1, min(max_docs, 20))

    evidence_docs = list(retrieved_documents[:max_docs])
    context_text = conversation_context or controller.build_conversation_context(chat_messages)
    use_llm_analysis = bool(getattr(controller.app_settings, "RAG_EVIDENCE_SYNTHESIS_ENABLED", True))

    parsed_analysis: Optional[Dict[str, Any]] = None
    if use_llm_analysis:
        try:
            system_prompt = controller.template_parser.get(template_group, "analysis_system_prompt", {}) or (
                "You are an evidence analyst. Return strict JSON only."
            )

            sections: List[str] = []
            char_budget = EVIDENCE_CHAR_BUDGET
            for idx, doc in enumerate(evidence_docs):
                if char_budget <= 0:
                    break
                chunk_text = (getattr(doc, "text", "") or "").strip()
                if not chunk_text:
                    continue
                chunk_text = controller.generation_client.process_text(chunk_text)
                if len(chunk_text) > char_budget:
                    chunk_text = chunk_text[:char_budget]
                char_budget -= len(chunk_text)
                doc_label = controller._resolve_document_label(
                    getattr(doc, "metadata", None),
                    fallback_label=f"Document {idx + 1}",
                    asset_labels=asset_labels,
                    asset_labels_by_name=asset_labels_by_name,
                )
                section = controller.template_parser.get(
                    template_group,
                    "document_prompt",
                    {"doc_label": doc_label, "chunk_text": chunk_text},
                ) or f"## Document: {doc_label}\n{chunk_text}"
                sections.append(section)

            analysis_footer = controller.template_parser.get(
                template_group,
                "analysis_footer_prompt",
                {"query": query, "conversation_context": context_text or ""},
            ) or (
                "Return strict JSON with keys: resolved_question, evidence_facts, "
                "candidate_answers, ambiguity_detected, ambiguity_reason, "
                "clarification_question, clarification_options, answer_confidence."
            )

            analysis_prompt = "\n\n".join([part for part in ["\n".join(sections), analysis_footer] if part])
            analysis_chat_history = [
                controller.generation_client.construct_prompt(
                    prompt=system_prompt,
                    role=controller.generation_client.enums.SYSTEM.value,
                )
            ]
            raw_analysis = controller.generation_client.generate_text(
                prompt=analysis_prompt,
                chat_history=analysis_chat_history,
                temperature=0.0,
            )
            parsed_analysis = extract_json_object(controller, raw_analysis)

            if parsed_analysis is None:
                retry_prompt = (
                    analysis_prompt
                    + "\n\nImportant: return one valid JSON object only. No markdown, no prose."
                )
                retry_output = controller.generation_client.generate_text(
                    prompt=retry_prompt,
                    chat_history=analysis_chat_history,
                    temperature=0.0,
                )
                parsed_analysis = extract_json_object(controller, retry_output)
        except Exception as exc:
            logger.error("Evidence analysis stage failed: %s", exc)
            parsed_analysis = None

    if parsed_analysis is None:
        normalized = build_heuristic_analysis(
            controller,
            query=query,
            documents=evidence_docs,
            asset_labels=asset_labels,
            asset_labels_by_name=asset_labels_by_name,
        )
        normalized["__analysis_source"] = "heuristic"
        normalized["__analysis_parse_failed"] = bool(use_llm_analysis)
    else:
        normalized = normalize_analysis_payload(controller, parsed_analysis, query)
        normalized["__analysis_source"] = "llm"
        normalized["__analysis_parse_failed"] = False

    logger.info(
        "RAG_ANALYSIS_PARSE template=%s used_llm=%s parse_failed=%s source=%s docs=%d",
        template_group,
        bool(use_llm_analysis),
        bool(normalized.get("__analysis_parse_failed", False)),
        normalized.get("__analysis_source"),
        len(evidence_docs),
    )

    return apply_ambiguity_gate(
        controller,
        analysis=normalized,
        query=query,
        ambiguity_threshold=ambiguity_threshold,
        top_n=getattr(controller.app_settings, "RAG_AMBIGUITY_TOP_N", 4),
    )
