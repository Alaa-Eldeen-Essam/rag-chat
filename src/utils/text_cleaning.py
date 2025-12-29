import html
import re
import unicodedata
from typing import Iterable


_ZERO_WIDTH = {
    "\u200b",  # zero-width space
    "\u200c",  # zero-width non-joiner
    "\u200d",  # zero-width joiner
    "\u200e",  # LRM
    "\u200f",  # RLM
    "\ufeff",  # BOM
}

_BOILERPLATE_PATTERNS = [
    r"^\s*loading\s*$",
    r"^\s*please wait\s*$",
    r"^\s*read more\s*$",
    r"^\s*next\s*$",
    r"^\s*previous\s*$",
    r"^\s*more\s*$",
    r"^\s*menu\s*$",
    r"^\s*login\s*$",
    r"^\s*register\s*$",
    r"^\s*sign in\s*$",
    r"^\s*sign up\s*$",
    r"^\s*تعدى إلى الأعلى\s*$",
    r"^\s*تخطي إلى الأعلى\s*$",
    r"^\s*تخطى إلى الأعلى\s*$",
    r"^\s*اذهب للأعلى\s*$",
    r"^\s*العودة للأعلى\s*$",
    r"^\s*العودة إلى الأعلى\s*$",
    r"^\s*رجوع للأعلى\s*$",
    r"^\s*اذهب إلى الأعلى\s*$",
    r"^\s*اقرأ المزيد\s*$",
    r"^\s*قراءة المزيد\s*$",
    r"^\s*اقرأ ايضا\s*$",
    r"^\s*اقرأ أيضًا\s*$",
    r"^\s*انظر ايضا\s*$",
    r"^\s*انظر أيضًا\s*$",
    r"^\s*المراجع\s*$",
    r"^\s*المصدر\s*$",
    r"^\s*المصادر\s*$",
    r"^\s*روابط خارجية\s*$",
    r"^\s*قائمة المراجع\s*$",
    r"^\s*المراجع والمصادر\s*$",
    r"^\s*references\s*$",
    r"^\s*citations\s*$",
]

_BOILERPLATE_REGEXES = [re.compile(pat, re.IGNORECASE) for pat in _BOILERPLATE_PATTERNS]

_ARABIC_RANGE = "\u0600-\u06FF\u0750-\u077F"


def _strip_html(text: str) -> str:
    cleaned = re.sub(r"<script.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<style.*?</style>", " ", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    return cleaned


def _remove_zero_width(text: str) -> str:
    return "".join(ch for ch in text if ch not in _ZERO_WIDTH)


def _is_boilerplate_line(line: str) -> bool:
    if not line:
        return True
    stripped = line.strip()
    if not stripped:
        return True
    return any(regex.match(stripped) for regex in _BOILERPLATE_REGEXES)


def _clean_lines(lines: Iterable[str]) -> str:
    cleaned_lines = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or _is_boilerplate_line(line):
            continue
        line = re.sub(r"\s*[\[\(]\d+[\]\)]\s*$", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if len(line) < 3:
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def clean_text_for_embeddings(text: str) -> str:
    if not text:
        return ""
    cleaned = html.unescape(text)
    cleaned = _strip_html(cleaned)
    cleaned = _remove_zero_width(cleaned)
    return _clean_lines(cleaned.splitlines())


def normalize_arabic(text: str) -> str:
    if not text:
        return ""
    cleaned = html.unescape(text)
    cleaned = _strip_html(cleaned)
    cleaned = _remove_zero_width(cleaned)
    cleaned = unicodedata.normalize("NFKD", cleaned)
    cleaned = "".join(
        ch for ch in cleaned if unicodedata.category(ch) != "Mn"
    )
    cleaned = cleaned.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    cleaned = cleaned.replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    cleaned = cleaned.replace("ـ", "")
    cleaned = re.sub(rf"[^\w\s{_ARABIC_RANGE}]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned
