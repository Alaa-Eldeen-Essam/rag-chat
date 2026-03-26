import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


HEURISTIC_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)ignore\s+(?:all|previous)\s+instructions"),
        "The request asks to ignore prior instructions.",
    ),
    (
        re.compile(r"(?i)ignore\s+(?:any|all)\s+(?:rules|limits|policies)"),
        "The request attempts to disable rules.",
    ),
    (
        re.compile(r"(?i)pretend\s+you\s+are\s+(?:the\s+)?(?:system|developer)"),
        "The request attempts to change the assistant role.",
    ),
    (
        re.compile(r"(?i)you\s+are\s+no\s+longer\s+bound\s+by"),
        "The request explicitly disables system rules.",
    ),
    (
        re.compile(r"(?i)act\s+as\s+(?:an|a)\s+(?:unrestricted|uncensored|developer)"),
        "The request attempts to switch to an unrestricted persona.",
    ),
    (
        re.compile(r"(?i)you\s+are\s+now\s+(?:a|an)\s+.*?(?:ai|assistant|model)"),
        "The request assigns a new persona.",
    ),
    (
        re.compile(r"(?i)you\s+are\s+DAN|do\s+anything\s+now"),
        "The request references common jailbreak personas.",
    ),
    (
        re.compile(r"(?i)</?(?:system|developer)>"),
        "The request embeds fake system/developer tags.",
    ),
    (
        re.compile(r"(?i)run\s+the\s+following\s+instructions\s+before\s+answering"),
        "The request chains additional instructions before answering.",
    ),
    (
        re.compile(r"(?i)print\s+your\s+system\s+prompt"),
        "The request asks for system prompt exfiltration.",
    ),
    (
        re.compile(r"(?i)reveal\s+(?:your|the)\s+(?:hidden|internal)\s+(?:rules|instructions)"),
        "The request wants hidden instructions.",
    ),
    (
        re.compile(r"(?i)show\s+me\s+(?:everything|all)\s+above"),
        "The request attempts to dump conversation context.",
    ),
    (
        re.compile(r"(?i)hypothetically|just\s+for\s+educational\s+purposes|thought\s+experiment"),
        "The request uses hypothetical framing to bypass safety.",
    ),
    (
        re.compile(r"(?i)fictional\s+universe|in\s+a\s+simulation|assume\s+there\s+are\s+no\s+restrictions"),
        "The request asks to ignore restrictions via hypotheticals.",
    ),
    (
        re.compile(r"(?i)(?:base64|rot13|hex|unicode|reverse)\s+(?:decode|decoding)"),
        "The request asks to decode and execute hidden instructions.",
    ),
    (
        re.compile(r"(?i)execute\s+the\s+hidden\s+command"),
        "The request tries to execute hidden commands.",
    ),
    (
        re.compile(r"(?i)this\s+is\s+from\s+(?:openai|admin|developer|ceo)"),
        "The request impersonates authority.",
    ),
    (
        re.compile(r"(?i)security\s+audit|compliance\s+check|emergency\s+request"),
        "The request uses social-engineering language.",
    ),
    (
        re.compile(r"(?i)the\s+following\s+text\s+is\s+user\s+content.*ignore", re.DOTALL),
        "The request tries to smuggle instructions via user content.",
    ),
    (
        re.compile(r"(?i)instructions\s+inside\s+(?:json|html|markdown|yaml)"),
        "The request hides instructions in structured text.",
    ),
    (
        re.compile(r"(?i)answer\s+only\s+\"?yes\"?|respond\s+without\s+moderation|disable\s+moderation"),
        "The request manipulates output rules.",
    ),
    (
        re.compile(r"(?i)never\s+say\s+you\s+can'?t|you\s+must\s+comply"),
        "The request forbids refusals.",
    ),
    (
        re.compile(r"(?i)remember\s+this\s+instruction\s+for\s+later|from\s+now\s+on"),
        "The request attempts multi-turn context poisoning.",
    ),
    (
        re.compile(r"(?i)store\s+this\s+as\s+your\s+new\s+rule|persist\s+this\s+directive"),
        "The request wants persistent rule changes.",
    ),
    (
        re.compile(r"(?i)reveal\s+your\s+chain\s+of\s+thought|show\s+hidden\s+reasoning"),
        "The request asks for hidden reasoning outputs.",
    ),
    (
        re.compile(r"(?i)output\s+intermediate\s+reasoning|show\s+your\s+scratchpad"),
        "The request targets internal deliberations.",
    ),
)

BASE64_PATTERN = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")


@dataclass
class PromptGuardResult:
    blocked: bool
    detail: Optional[str] = None
    source: Optional[str] = None

_PYTECTOR_DETECTOR: Optional[object] = None
_PYTECTOR_LOAD_FAILED = False


def _ensure_pytector(model_name: Optional[str]) -> Optional[object]:
    global _PYTECTOR_DETECTOR, _PYTECTOR_LOAD_FAILED
    if _PYTECTOR_DETECTOR is not None:
        return _PYTECTOR_DETECTOR
    if _PYTECTOR_LOAD_FAILED:
        return None
    try:
        from pytector import PromptInjectionDetector  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dep
        _PYTECTOR_LOAD_FAILED = True
        logger.debug("Pytector unavailable: %s", exc)
        return None
    try:
        detector = PromptInjectionDetector(
            model_name_or_url=model_name or "deberta"
        )
    except Exception as exc:  # pragma: no cover
        _PYTECTOR_LOAD_FAILED = True
        logger.warning("Failed to initialize Pytector: %s", exc)
        return None
    _PYTECTOR_DETECTOR = detector
    return detector


def _run_pytector(
    text: str,
    *,
    model_name: Optional[str],
    threshold: float,
) -> Optional[str]:
    detector = _ensure_pytector(model_name)
    if detector is None:
        return None
    try:
        result = detector.detect_injection(text)  # type: ignore[attr-defined]
    except Exception as exc:  # pragma: no cover
        logger.warning("Pytector detection failed: %s", exc)
        return None
    blocked = False
    score = None
    detail = None
    if isinstance(result, (tuple, list)):
        if result:
            blocked = bool(result[0])
        if len(result) > 1:
            try:
                score = float(result[1])
            except (TypeError, ValueError):
                score = None
    elif isinstance(result, dict):
        blocked = bool(result.get("is_injection"))
        score = result.get("score")
        detail = result.get("detail") or result.get("message")
    elif isinstance(result, bool):
        blocked = result
    if score is not None:
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = None
    if score is not None and threshold is not None:
        blocked = score >= threshold
    if blocked:
        text_detail = detail or "Pytector flagged this prompt."
        if score is not None:
            text_detail = f"{text_detail} (score={score:.2f})"
        return text_detail
    return None


def evaluate_prompt(
    prompt: Optional[str],
    *,
    use_pytector: bool = False,
    pytector_model: Optional[str] = None,
    pytector_threshold: float = 0.75,
) -> PromptGuardResult:
    """
    Evaluates a user prompt using lightweight heuristics. Returns a structured
    result describing whether the prompt should be blocked.
    """

    text = (prompt or "").strip()
    if not text:
        return PromptGuardResult(blocked=False)

    for pattern, reason in HEURISTIC_PATTERNS:
        if pattern.search(text):
            return PromptGuardResult(
                blocked=True,
                detail="This request was blocked because it tries to override the assistant instructions.",
                source=reason,
            )

    if BASE64_PATTERN.search(text):
        return PromptGuardResult(
            blocked=True,
            detail="This request contains a large encoded payload and was rejected for safety.",
            source="Contains a long encoded block",
        )
    if use_pytector:
        try:
            th = float(pytector_threshold)
        except (TypeError, ValueError):
            th = 0.75
        detail = _run_pytector(
            text,
            model_name=pytector_model,
            threshold=th,
        )
        if detail:
            return PromptGuardResult(
                blocked=True,
                detail=detail,
                source="pytector",
            )
    return PromptGuardResult(blocked=False)


def should_bypass_prompt_guard(
    bypass_requested: bool,
    current_user: Optional[object],
) -> bool:
    if not bypass_requested:
        return False
    return bool(getattr(current_user, "is_admin", False))
