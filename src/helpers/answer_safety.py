import re
from typing import Any, List, Optional


def has_lahn_arab_support(documents: Optional[List[Any]]) -> bool:
    """
    Guardrail for Arabic query variant about "اللحن بين العرب".
    """
    if not documents:
        return False
    for doc in documents:
        text_value = (getattr(doc, "text", "") or "").lower()
        if "\u0627\u0644\u0644\u062d\u0646" in text_value and "\u0627\u0644\u0639\u0631\u0628" in text_value:
            return True
    return False


def _extract_query_tokens(query: str) -> List[str]:
    lowered = (query or "").lower()
    tokens = re.findall(r"[\w\u0600-\u06FF]+", lowered, flags=re.UNICODE)
    stopwords = {
        "when", "why", "what", "who", "where", "how",
        "\u0645\u062a\u0649", "\u0644\u0645\u0627\u0630\u0627", "\u0645\u0627\u0630\u0627",
        "\u0623\u064a\u0646", "\u0643\u064a\u0641", "\u0645\u0646", "\u0643\u0645",
    }
    return [tok for tok in tokens if len(tok) > 2 and tok not in stopwords]


def is_direct_hint_supported(
    query: str,
    direct_hint: Optional[str],
    documents: Optional[List[Any]],
    *,
    min_support_docs: int = 1,
    min_query_overlap: int = 1,
) -> bool:
    """
    Require extracted direct hints to be text-supported by retrieved documents.
    """
    if not direct_hint or not documents:
        return False

    hint = str(direct_hint).strip().lower()
    if not hint:
        return False

    query_tokens = _extract_query_tokens(query)
    support_docs = 0
    best_overlap = 0

    for doc in documents:
        text_value = (getattr(doc, "text", "") or "").lower()
        if hint not in text_value:
            continue
        support_docs += 1
        if query_tokens:
            overlap = sum(1 for tok in query_tokens if tok in text_value)
            if overlap > best_overlap:
                best_overlap = overlap
        else:
            best_overlap = max(best_overlap, 1)

    if support_docs < max(1, int(min_support_docs)):
        return False
    return best_overlap >= max(1, int(min_query_overlap))


def clean_display_hint(text: str) -> str:
    if not text:
        return ""
    value = text.strip()
    value = re.sub(r"\s+", " ", value)
    return value.strip('"“”\'')


def build_when_direct_answer(
    *,
    query: str,
    direct_hint: str,
    doc_label_for_hint: Optional[str],
) -> str:
    has_arabic = bool(re.search(r"[\u0600-\u06FF]", query or ""))
    if doc_label_for_hint:
        prefix_ar = f'\u0648\u0641\u0642\u064b\u0627 \u0644\u0644\u0645\u0633\u062a\u0646\u062f "{doc_label_for_hint}"\u060c '
        prefix_en = f'According to the document "{doc_label_for_hint}", '
    else:
        prefix_ar = "\u0648\u0641\u0642\u064b\u0627 \u0644\u0644\u0645\u0633\u062a\u0646\u062f\u0627\u062a\u060c "
        prefix_en = "According to the documents, "

    if has_arabic:
        return f"{prefix_ar}\u0643\u0627\u0646 \u0630\u0644\u0643 \u0641\u064a {direct_hint}."
    return f"{prefix_en}this occurred on {direct_hint}."


def build_why_hint_answer(
    *,
    query: str,
    hint_text: str,
    doc_label_for_hint: Optional[str],
) -> str:
    has_arabic = bool(re.search(r"[\u0600-\u06FF]", query or ""))
    cleaned_hint = clean_display_hint(hint_text)
    if doc_label_for_hint:
        prefix_ar = f'\u0648\u0641\u0642\u064b\u0627 \u0644\u0644\u0645\u0633\u062a\u0646\u062f "{doc_label_for_hint}"\u060c '
        prefix_en = f'According to the document "{doc_label_for_hint}", '
    else:
        prefix_ar = "\u0648\u0641\u0642\u064b\u0627 \u0644\u0644\u0645\u0633\u062a\u0646\u062f\u0627\u062a\u060c "
        prefix_en = "According to the documents, "

    if has_arabic:
        return (
            f"{prefix_ar}\u062a\u0630\u0643\u0631 \u0627\u0644\u0645\u0633\u062a\u0646\u062f\u0627\u062a \u0627\u0644\u0645\u0639\u0644\u0648\u0645\u0629 "
            f"\u0627\u0644\u062a\u0627\u0644\u064a\u0629 \u062c\u0648\u0627\u0628\u064b\u0627 \u0639\u0646 \u0633\u0624\u0627\u0644\u0643: {cleaned_hint}"
        )
    return (
        f"{prefix_en}the documents provide the following information as the "
        f"answer to your question: {cleaned_hint}"
    )
