import re
from typing import Any, List, Optional

AR_MONTHS_PATTERN = (
    "\u064a\u0646\u0627\u064a\u0631|\u0641\u0628\u0631\u0627\u064a\u0631|\u0645\u0627\u0631\u0633|\u0623\u0628\u0631\u064a\u0644|\u0627\u0628\u0631\u064a\u0644|\u0645\u0627\u064a\u0648|\u064a\u0648\u0646\u064a\u0648|\u064a\u0648\u0644\u064a\u0648|"
    "\u0623\u063a\u0633\u0637\u0633|\u0627\u063a\u0633\u0637\u0633|\u0633\u0628\u062a\u0645\u0628\u0631|\u0623\u0643\u062a\u0648\u0628\u0631|\u0627\u0643\u062a\u0648\u0628\u0631|\u0646\u0648\u0641\u0645\u0628\u0631|\u062f\u064a\u0633\u0645\u0628\u0631"
)
EN_MONTHS_PATTERN = (
    "January|February|March|April|May|June|July|August|September|October|November|December|"
    "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)
DATE_REGEX = re.compile(
    rf"("
    rf"\d{{1,2}}\D{{0,7}}(?:{AR_MONTHS_PATTERN}|{EN_MONTHS_PATTERN})\D{{0,7}}\d{{4}}"
    rf"|"
    rf"(?:{AR_MONTHS_PATTERN}|{EN_MONTHS_PATTERN})\D{{0,7}}\d{{4}}"
    rf")"
)


def detect_question_type(query: str) -> str:
    if not query:
        return ""

    q = (query or "").strip().lower()

    if "\u0645\u062a\u0649" in q or q.startswith("when "):
        return "when"

    if (
        "\u0644\u0645\u0627\u0630\u0627" in q
        or "\u0644\u0645\u0627\u0630\u0627 \u0644\u0645" in q
        or q.startswith("why ")
        or "\u0645\u0627 \u0633\u0628\u0628" in q
        or "\u0645\u0627 \u0647\u0648 \u0633\u0628\u0628" in q
        or "\u0645\u0627 \u0647\u064a \u0623\u0633\u0628\u0627\u0628" in q
        or "\u0645\u0627 \u0627\u0644\u0627\u0633\u0628\u0627\u0628" in q
        or "\u0645\u0627 \u0627\u0644\u0623\u0633\u0628\u0627\u0628" in q
        or "\u0645\u0627 \u0627\u0644\u0630\u064a \u062f\u0641\u0639" in q
        or "what is the reason" in q
        or "what's the reason" in q
        or "what is the cause" in q
        or "what caused" in q
    ):
        return "why"

    if "\u0623\u064a\u0646" in q or q.startswith("where "):
        return "where"

    if "\u0645\u0646 " in q or q.startswith("who "):
        return "who"

    if "\u0643\u0645 " in q or "how many" in q:
        return "how_many"

    return ""


def try_extract_direct_answer(query: str, documents: List[Any], question_type: str) -> Optional[str]:
    if not query or not documents or not question_type:
        return None

    corpus = "\n".join((getattr(doc, "text", "") or "") for doc in documents)
    if not corpus:
        return None

    if question_type == "when":
        sentences = re.split(r"[\.!\?\u061f\n]+", corpus)
        lowered_query = (query or "").lower()
        stop_tokens = {"\u0645\u062a\u0649", "when", "?", "\u061f"}
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

            overlap = sum(1 for tok in query_tokens if tok in low)
            if overlap > best_overlap:
                best_overlap = overlap
                best_candidate = date_candidate

        if best_candidate and best_overlap > 0:
            return best_candidate
        return None

    if question_type == "why":
        sentences = re.split(r"[\.!\?\u061f\n]+", corpus)

        def normalize_arabic(text: str) -> str:
            text = re.sub(r"[\u064b\u064c\u064d\u064e\u064f\u0650\u0651\u0652\u0640]", "", text)
            text = text.replace("\u0623", "\u0627").replace("\u0625", "\u0627").replace("\u0622", "\u0627")
            text = text.replace("\u0649", "\u064a").replace("\u0629", "\u0647")
            return re.sub(r"\s+", " ", text)

        travel_keywords = [
            "\u0633\u0627\u0641\u0631",
            "\u0630\u0647\u0628",
            "\u062a\u0648\u062c\u0647",
            "\u0632\u0627\u0631",
            "\u0631\u062d\u0644",
            "\u0633\u0641\u0631",
            "\u0632\u064a\u0627\u0631\u0629",
            "traveled",
            "travelled",
            "went",
            "visited",
            "journeyed",
        ]

        purpose_pattern = re.compile(
            r"(\u0644[\u0627\u0623\u0625\u0622\u0628\u062a\u062b\u062c\u062d\u062e\u062f\u0630\u0631\u0632\u0633\u0634\u0635\u0636\u0637\u0638\u0639\u063a\u0641\u0642\u0643\u0644\u0645\u0646\u0647\u0648\u064a]{2,8}\s*"
            r"(?:\u0627\u062c\u062a\u0645\u0627\u0639|\u0627\u062c\u062a\u0645\u0627\u0639\u0627|\u0645\u0624\u062a\u0645\u0631|\u0642\u0645\u0629|\u0644\u0642\u0627\u0621|meeting|summit|conference))",
            flags=re.IGNORECASE,
        )

        triggers = [
            "\u0644\u062d\u0636\u0648\u0631",
            "\u0644\u0644\u0645\u0634\u0627\u0631\u0643\u0629",
            "\u0644\u062a\u0642\u062f\u064a\u0645",
            "\u0644\u0644\u062a\u0641\u0627\u0648\u0636",
            "\u0644\u0639\u0642\u062f",
            "\u0645\u0646 \u0627\u062c\u0644",
            "\u0628\u0647\u062f\u0641",
            "\u0644\u0627\u0646",
            "\u0644\u0623\u0646",
            "\u0628\u0633\u0628\u0628",
            "\u0646\u062a\u064a\u062c\u0647",
            "\u0646\u062a\u064a\u062c\u0629",
            "to attend",
            "in order to",
            "for the purpose of",
            "because",
            "because of",
            "due to",
            "as a result of",
        ]

        lowered_query = (query or "").lower()
        normalized_query = normalize_arabic(lowered_query)
        stop_tokens = {"\u0644\u0645\u0627\u0630\u0627", "why", "?", "\u061f"}
        query_tokens = [
            tok
            for tok in re.findall(r"\w+", normalized_query, flags=re.UNICODE)
            if tok not in stop_tokens and len(tok) > 2
        ]

        for sent in sentences:
            s = sent.strip()
            if not s:
                continue
            low = s.lower()
            norm = normalize_arabic(low)
            if not any(tv in norm for tv in travel_keywords):
                continue
            if query_tokens and not any(tok in norm for tok in query_tokens):
                continue

            m = purpose_pattern.search(low)
            if m:
                start = m.start()
                tail = s[start:]
                p = re.search(r"[\.!\?\u061f]", tail)
                end = start + p.start() if p else len(s)
                reason_fragment = s[start:end].strip()
                if reason_fragment:
                    return reason_fragment

        best_sentence = None
        for sent in sentences:
            s = sent.strip()
            if not s:
                continue
            low = s.lower()
            norm = normalize_arabic(low)
            if any(trigger in norm for trigger in triggers):
                if query_tokens and any(tok in norm for tok in query_tokens):
                    best_sentence = s
                    break
                if best_sentence is None:
                    best_sentence = s

        if best_sentence:
            return best_sentence.strip()

    if question_type == "where":
        sentences = re.split(r"[\.!\?\u061f\n]+", corpus)

        def normalize_arabic(text: str) -> str:
            text = re.sub(r"[\u064b\u064c\u064d\u064e\u064f\u0650\u0651\u0652\u0640]", "", text)
            text = text.replace("\u0623", "\u0627").replace("\u0625", "\u0627").replace("\u0622", "\u0627")
            text = text.replace("\u0649", "\u064a").replace("\u0629", "\u0647")
            return re.sub(r"\s+", " ", text)

        lowered_query = (query or "").lower()
        norm_query = normalize_arabic(lowered_query)
        stop_tokens = {"\u0627\u064a\u0646", "\u0623\u064a\u0646", "where", "?", "\u061f"}
        query_tokens = [
            tok
            for tok in re.findall(r"\w+", norm_query, flags=re.UNICODE)
            if tok not in stop_tokens and len(tok) > 2
        ]

        location_markers = ["\u0641\u064a ", "\u0641\u064a-", "\u0627\u0644\u0649 ", "\u0625\u0644\u0649 ", "near", " in ", " at ", " to "]

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
            score += sum(1 for tok in query_tokens if tok in norm)

            if score > best_score:
                best_score = score
                best_sentence = s

        if best_sentence and best_score > 0:
            return best_sentence.strip()

    if question_type == "how_many":
        sentences = re.split(r"[\.!\?\u061f\n]+", corpus)
        lowered_query = (query or "").lower()
        stop_tokens = {"\u0643\u0645", "how", "many", "?", "\u061f"}
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

            overlap = sum(1 for tok in query_tokens if tok in low)
            if overlap > best_score:
                best_score = overlap
                best_sentence = s

        if best_sentence and best_score > 0:
            return best_sentence.strip()

    return None
