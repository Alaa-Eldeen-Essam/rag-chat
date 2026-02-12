from typing import Optional


def normalize_answer_style(style: Optional[str]) -> str:
    normalized = (style or "").strip().lower()
    if normalized in {"concise", "detailed", "balanced"}:
        return normalized
    return "concise"


def infer_answer_style(controller, query: Optional[str], explicit_style: Optional[str] = None) -> str:
    """
    Infer answer style from user question (Arabic + English hints).
    Explicit style, if provided, wins; otherwise use heuristics.
    """
    if explicit_style:
        return normalize_answer_style(explicit_style)

    q = (query or "").strip().lower()
    if not q:
        return "balanced"

    # English concise cues
    concise_en = [
        "short answer", "concise", "brief", "summary", "summarize", "tl;dr",
        "in short", "quick answer", "quickly", "few words"
    ]
    # Arabic concise cues
    concise_ar = [
        "\u0645\u062e\u062a\u0635\u0631", "\u0628\u0627\u062e\u062a\u0635\u0627\u0631",
        "\u0628\u0625\u064a\u062c\u0627\u0632", "\u0645\u0644\u062e\u0635",
        "\u062a\u0644\u062e\u064a\u0635", "\u062e\u0644\u0627\u0635\u0629",
        "\u0642\u0635\u064a\u0631", "\u0625\u062c\u0627\u0628\u0629 \u0642\u0635\u064a\u0631\u0629",
    ]

    # English detailed cues
    detailed_en = [
        "detailed", "in detail", "elaborate", "explain fully", "step by step",
        "comprehensive", "long answer", "deep dive", "full explanation"
    ]
    # Arabic detailed cues
    detailed_ar = [
        "\u0628\u0627\u0644\u062a\u0641\u0635\u064a\u0644", "\u062a\u0641\u0635\u064a\u0644\u064a",
        "\u0627\u0634\u0631\u062d", "\u0634\u0631\u062d", "\u0645\u0648\u0633\u0639",
        "\u0645\u0637\u0648\u0644", "\u0628\u062a\u0648\u0633\u0639", "\u0643\u0627\u0645\u0644\u0629",
        "\u062a\u0641\u0627\u0635\u064a\u0644",
    ]

    def any_in(tokens):
        return any(tok in q for tok in tokens)

    detailed_hit = any_in(detailed_en) or any_in(detailed_ar)
    concise_hit = any_in(concise_en) or any_in(concise_ar)

    if detailed_hit and not concise_hit:
        return "detailed"
    if concise_hit and not detailed_hit:
        return "concise"
    if detailed_hit and concise_hit:
        return "balanced"
    return "balanced"


def build_style_directives(
    controller,
    answer_style: Optional[str],
    explain_retrieval: bool,
    language: str,
) -> tuple[str, str]:
    """
    Build bilingual (EN/AR) style hints that get injected into the prompts.
    """
    style = normalize_answer_style(answer_style)
    lang = (language or "").lower()
    is_ar = lang.startswith("ar")

    if style == "detailed":
        style_hint_en = "Detailed answer with clear structure; use bullet/numbered points when helpful."
        style_hint_ar = "\u0625\u062c\u0627\u0628\u0629 \u0645\u0641\u0635\u0644\u0629 \u0648\u0645\u0646\u0638\u0645\u0629\u061b \u0627\u0633\u062a\u062e\u062f\u0645 \u0646\u0642\u0627\u0637\u064b\u0627 \u0623\u0648 \u062a\u0631\u0642\u064a\u0645\u064b\u0627 \u0639\u0646\u062f \u0627\u0644\u062d\u0627\u062c\u0629."
    elif style == "balanced":
        style_hint_en = "Balanced answer: a short summary followed by key details."
        style_hint_ar = "\u0625\u062c\u0627\u0628\u0629 \u0645\u062a\u0648\u0627\u0632\u0646\u0629: \u0645\u0644\u062e\u0635 \u0642\u0635\u064a\u0631 \u064a\u062a\u0628\u0639\u0647 \u0623\u0647\u0645 \u0627\u0644\u062a\u0641\u0627\u0635\u064a\u0644."
    else:
        style_hint_en = "Concise answer: keep it direct and short."
        style_hint_ar = "\u0625\u062c\u0627\u0628\u0629 \u0645\u0648\u062c\u0632\u0629: \u0645\u062e\u062a\u0635\u0631\u0629 \u0648\u0645\u0628\u0627\u0634\u0631\u0629."

    explain_en = ""
    explain_ar = ""
    if explain_retrieval:
        explain_en = "Start with a brief evidence recap (1-2 sentences) before the final answer."
        explain_ar = "\u0627\u0628\u062f\u0623 \u0628\u0645\u0644\u062e\u0635 \u0642\u0635\u064a\u0631 \u0644\u0644\u0623\u062f\u0644\u0629 (\u0661-\u0662 \u062c\u0645\u0644\u0629) \u0642\u0628\u0644 \u0627\u0644\u0625\u062c\u0627\u0628\u0629 \u0627\u0644\u0646\u0647\u0627\u0626\u064a\u0629."

    style_instructions = style_hint_ar if is_ar else style_hint_en
    if explain_retrieval:
        style_instructions = f"{style_instructions} {explain_ar if is_ar else explain_en}".strip()

    style_hint = style_hint_ar if is_ar else style_hint_en
    if explain_retrieval:
        hint_suffix = "+ evidence recap first"
        if is_ar:
            hint_suffix = "\u002b \u0645\u0644\u062e\u0635 \u0623\u062f\u0644\u0629 \u0623\u0648\u0644\u0627\u064b"
        style_hint = f"{style_hint} {hint_suffix}"

    return style_instructions, style_hint
